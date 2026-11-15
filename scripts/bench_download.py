"""Benchmark the gallery-dl download stage with the bot's own command line.

The script never reads or writes the SQLite cache and never talks to Telegram,
so every run is a real cache miss of the download stage only.

    uv run --frozen python scripts/bench_download.py --repeats 5 URL [URL ...]

Settings (COOKIES_FILE, INSTAGRAM_USER, USE_ARIA2, ...) are taken from the
environment / .env exactly as the bot does. Output contains no cookies, tokens
or gallery-dl stderr text - only timings, counters and host names.
"""

import argparse
import asyncio
import json
import os
import platform
import re
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:benchmark-placeholder")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import settings
from downloader.gallery import _build_cmd, _collect_media
from utils import clean_url

CONNECT_RE = re.compile(r"Starting new HTTPS connection \(\d+\): ([^:\s]+)")
SLEEP_RE = re.compile(r"Sleeping (\d+(?:\.\d+)?) seconds")


@dataclass(slots=True)
class Run:
    url: str
    ok: bool = False
    returncode: int | None = None
    wall_s: float = 0.0
    startup_s: float | None = None
    extract_s: float | None = None
    download_s: float | None = None
    sleep_s: float = 0.0
    fallbacks: int = 0
    ytdl_missing: bool = False
    files: int = 0
    videos: int = 0
    bytes: int = 0
    media_hosts: list[str] = field(default_factory=list)
    cpu_s: float | None = None
    max_loop_lag_ms: float = 0.0


async def _loop_lag(stop: asyncio.Event, out: list[float]) -> None:
    interval = 0.01
    worst = 0.0
    while not stop.is_set():
        start = time.perf_counter()
        await asyncio.sleep(interval)
        worst = max(worst, time.perf_counter() - start - interval)
    out.append(worst * 1000)


async def run_once(url: str, root: Path, measure_cpu: bool) -> Run:
    run = Run(url=url)
    work_dir = Path(tempfile.mkdtemp(dir=root, prefix="bench-"))
    site_host = urlparse(url).netloc.lower()
    cmd = [*_build_cmd(work_dir), "--verbose", "--", url]

    stop = asyncio.Event()
    lag: list[float] = []
    lag_task = asyncio.create_task(_loop_lag(stop, lag))
    cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)

    t0 = time.perf_counter()
    t_first: float | None = None
    t_media: float | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        if proc.stderr is None:
            raise RuntimeError("stderr pipe is missing")

        async def read_stderr() -> None:
            nonlocal t_first, t_media
            stream = proc.stderr
            if stream is None:
                return
            async for raw in stream:
                now = time.perf_counter()
                line = raw.decode(errors="replace")
                if t_first is None:
                    t_first = now
                if match := CONNECT_RE.search(line):
                    host = match.group(1).lower()
                    is_site = host == site_host or host in {
                        "www.tiktok.com",
                        "www.instagram.com",
                        "i.instagram.com",
                    }
                    if not is_site:
                        if t_media is None:
                            t_media = now
                        if host not in run.media_hosts:
                            run.media_hosts.append(host)
                if match := SLEEP_RE.search(line):
                    run.sleep_s += float(match.group(1))
                if "Trying fallback URL" in line:
                    run.fallbacks += 1
                if "Cannot import yt-dlp" in line:
                    run.ytdl_missing = True

        await asyncio.wait_for(
            asyncio.gather(read_stderr(), proc.wait()),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )
        run.returncode = proc.returncode
    except TimeoutError:
        proc.kill()
        await proc.wait()
    finally:
        t_end = time.perf_counter()
        stop.set()
        await lag_task

    run.wall_s = t_end - t0
    run.max_loop_lag_ms = lag[0] if lag else 0.0
    if t_first is not None:
        run.startup_s = t_first - t0
    if t_media is not None:
        run.extract_s = t_media - t0
        run.download_s = t_end - t_media
    if measure_cpu:
        cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        run.cpu_s = (cpu_after.ru_utime - cpu_before.ru_utime) + (
            cpu_after.ru_stime - cpu_before.ru_stime
        )

    media = _collect_media(work_dir)
    run.files = len(media)
    run.videos = sum(1 for item in media if item.is_video)
    run.bytes = sum(item.path.stat().st_size for item in media)
    run.ok = run.returncode == 0 and run.files > 0
    shutil.rmtree(work_dir, ignore_errors=True)
    return run


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
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
        "gallery_dl": out([settings.gallery_dl_bin, "--version"]),
        "ffmpeg": out(["ffmpeg", "-version"]),
        "platform": platform.platform(),
        "cpus": str(os.cpu_count()),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between batches")
    parser.add_argument("--json", type=Path, help="write raw runs to this file")
    args = parser.parse_args()

    urls = [clean_url(u.strip()) for u in args.urls]
    root = Path(tempfile.mkdtemp(prefix="tg-bench-"))
    config = {
        "repeats": args.repeats,
        "concurrency": args.concurrency,
        "use_aria2": settings.USE_ARIA2,
        "cookies_file_present": Path(settings.COOKIES_FILE).is_file(),
        "instagram_login_configured": bool(settings.INSTAGRAM_USER and settings.INSTAGRAM_PASS),
        "download_timeout": settings.DOWNLOAD_TIMEOUT,
    }
    versions = _versions()
    print(json.dumps({"versions": versions, "config": config}, ensure_ascii=False))  # noqa: T201

    runs: list[Run] = []
    jobs = [url for _ in range(args.repeats) for url in urls]
    try:
        for start in range(0, len(jobs), args.concurrency):
            batch = jobs[start : start + args.concurrency]
            done = await asyncio.gather(
                *(run_once(u, root, measure_cpu=len(batch) == 1) for u in batch)
            )
            runs.extend(done)
            for r in done:
                print(  # noqa: T201
                    f"{'ok ' if r.ok else 'ERR'} {r.wall_s:6.2f}s "
                    f"files={r.files} {r.bytes / 1e6:6.2f}MB {r.url}",
                    flush=True,
                )
            if start + args.concurrency < len(jobs):
                await asyncio.sleep(args.pause)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    header = (
        f"{'url':<46} {'ok':>5} {'MB':>6} {'files':>5}  "
        "wall p50/p95 startup      extract      download     cpu          sleep"
    )
    print("\n" + header)  # noqa: T201
    for url in urls:
        group = [r for r in runs if r.url == url]
        good = [r for r in group if r.ok]
        size = statistics.median([r.bytes for r in good]) / 1e6 if good else 0.0
        files = good[0].files if good else 0
        print(  # noqa: T201
            f"{url[-46:]:<46} {len(good):>2}/{len(group):<2} {size:6.2f} {files:>5}  "
            f"{_stat(good, 'wall_s')}{_stat(good, 'startup_s')}{_stat(good, 'extract_s')}"
            f"{_stat(good, 'download_s')}{_stat(good, 'cpu_s')}{_stat(good, 'sleep_s')}"
        )
    worst_lag = max((r.max_loop_lag_ms for r in runs), default=0.0)
    print(f"\nmax event-loop lag: {worst_lag:.1f} ms; runs: {len(runs)}")  # noqa: T201

    if args.json:
        payload = {"versions": versions, "config": config, "runs": [asdict(r) for r in runs]}
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0 if all(r.ok for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
