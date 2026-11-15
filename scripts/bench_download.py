"""Benchmark the download stage through the bot's own downloader.

The script never reads or writes the SQLite cache and never talks to Telegram,
so every run is a real cache miss of the download stage only. gallery-dl runs
inside this process, as in the bot: the first run per site pays for new
connections, later runs reuse them, so both are reported.

    uv run --frozen python scripts/bench_download.py --repeats 5 URL [URL ...]

Settings (COOKIES_FILE, INSTAGRAM_USER, DOWNLOAD_TIMEOUT, ...) are taken from
the environment / .env exactly as the bot does. Output contains no cookies or
tokens - only timings, sizes and counters.
"""

import argparse
import asyncio
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:benchmark-placeholder")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import structlog

from config import settings
from downloader.gallery import cleanup, download_media
from utils import clean_url


@dataclass(slots=True)
class Run:
    url: str
    round: int
    ok: bool
    wall_s: float
    extract_s: float | None
    fetch_s: float | None
    files: int
    videos: int
    bytes: int
    max_loop_lag_ms: float


async def _loop_lag(stop: asyncio.Event, out: list[float]) -> None:
    interval = 0.01
    worst = 0.0
    while not stop.is_set():
        start = time.perf_counter()
        await asyncio.sleep(interval)
        worst = max(worst, time.perf_counter() - start - interval)
    out.append(worst * 1000)


async def run_once(url: str, round_no: int) -> Run:
    stop = asyncio.Event()
    lag: list[float] = []
    lag_task = asyncio.create_task(_loop_lag(stop, lag))
    started = time.perf_counter()
    try:
        result = await download_media(url)
    finally:
        wall = time.perf_counter() - started
        stop.set()
        await lag_task

    extract = result.timings.get("extract_ms")
    fetch = result.timings.get("fetch_ms")
    run = Run(
        url=url,
        round=round_no,
        ok=result.success,
        wall_s=wall,
        extract_s=extract / 1000 if extract is not None else None,
        fetch_s=fetch / 1000 if fetch is not None else None,
        files=len(result.media_files),
        videos=sum(1 for item in result.media_files if item.is_video),
        bytes=sum(item.path.stat().st_size for item in result.media_files),
        max_loop_lag_ms=lag[0] if lag else 0.0,
    )
    if result.work_dir:
        cleanup(result.work_dir)
    return run


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _stat(runs: list[Run], attr: str) -> str:
    values = [v for r in runs if (v := getattr(r, attr)) is not None]
    if not values:
        return "    n/a     "
    return f"{statistics.median(values):5.2f}/{_pct(values, 0.95):5.2f} "


def _versions() -> dict[str, str]:
    def out(cmd: list[str]) -> str:
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
        except OSError:
            return "missing"
        lines = (done.stdout or done.stderr).strip().splitlines()
        return lines[0] if lines else "missing"

    root = Path(__file__).resolve().parent.parent
    return {
        "commit": out(["git", "-C", str(root), "rev-parse", "--short", "HEAD"]),
        "python": platform.python_version(),
        "gallery_dl": version("gallery-dl"),
        "ffmpeg": out(["ffmpeg", "-version"]),
        "platform": platform.platform(),
        "cpus": str(os.cpu_count()),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between batches")
    parser.add_argument("--json", type=Path, help="write raw runs to this file")
    args = parser.parse_args()

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))
    urls = [clean_url(u.strip()) for u in args.urls]
    config = {
        "repeats": args.repeats,
        "concurrency": args.concurrency,
        "pause": args.pause,
        "cookies_file_present": Path(settings.COOKIES_FILE).is_file(),
        "instagram_login_configured": bool(settings.INSTAGRAM_USER and settings.INSTAGRAM_PASS),
        "download_timeout": settings.DOWNLOAD_TIMEOUT,
    }
    versions = _versions()
    print(json.dumps({"versions": versions, "config": config}, ensure_ascii=False))  # noqa: T201

    runs: list[Run] = []
    jobs = [(url, round_no) for round_no in range(args.repeats) for url in urls]
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    for start in range(0, len(jobs), args.concurrency):
        batch = jobs[start : start + args.concurrency]
        done = await asyncio.gather(*(run_once(url, round_no) for url, round_no in batch))
        runs.extend(done)
        for r in done:
            print(  # noqa: T201
                f"{'ok ' if r.ok else 'ERR'} {r.wall_s:6.2f}s "
                f"files={r.files} {r.bytes / 1e6:6.2f}MB {r.url}",
                flush=True,
            )
        if start + args.concurrency < len(jobs):
            await asyncio.sleep(args.pause)
    cpu_after = resource.getrusage(resource.RUSAGE_SELF)
    cpu = (cpu_after.ru_utime - cpu_before.ru_utime) + (cpu_after.ru_stime - cpu_before.ru_stime)

    print(  # noqa: T201
        f"\n{'url':<46} {'ok':>5} {'MB':>6} {'files':>5}  "
        "first    later runs p50/p95: wall  extract      fetch"
    )
    for url in urls:
        group = [r for r in runs if r.url == url]
        good = [r for r in group if r.ok]
        first = next((r for r in good if r.round == 0), None)
        later = [r for r in good if r.round > 0]
        size = statistics.median([r.bytes for r in good]) / 1e6 if good else 0.0
        print(  # noqa: T201
            f"{url[-46:]:<46} {len(good):>2}/{len(group):<2} {size:6.2f} "
            f"{good[0].files if good else 0:>5}  "
            f"{f'{first.wall_s:5.2f}' if first else '  n/a'}                  "
            f"{_stat(later, 'wall_s')}{_stat(later, 'extract_s')}{_stat(later, 'fetch_s')}"
        )
    worst_lag = max((r.max_loop_lag_ms for r in runs), default=0.0)
    print(  # noqa: T201
        f"\nmax event-loop lag: {worst_lag:.1f} ms; runs: {len(runs)}; "
        f"process CPU: {cpu:.2f} s; peak RSS: {cpu_after.ru_maxrss / 1024:.0f} MB"
    )

    if args.json:
        payload = {"versions": versions, "config": config, "runs": [asdict(r) for r in runs]}
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0 if all(r.ok for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
