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

# flake8: noqa: WPS201, WPS476
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import structlog

from config import settings
from downloader.gallery import cleanup, download_media
from utils import clean_url

ROOT = Path(__file__).resolve().parents[1]

MS_PER_SECOND = 1000
BYTES_PER_MB = 1_000_000
KIB_PER_MIB = 1024
P95 = 0.95
LOG_LEVEL_ERROR = 40
URL_WIDTH = 46
COMMAND_TIMEOUT_S = 20
LAG_INTERVAL_S = 0.01
DEFAULT_REPEATS = 5
DEFAULT_PAUSE_S = 2.0
NO_LAG_MS = 0
TABLE_HEADER = (
    "\n"
    + "url".ljust(URL_WIDTH)
    + "    ok     MB files  first    later runs p50/p95: wall  extract      fetch"
)
NOT_AVAILABLE = "    n/a     "


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


@dataclass(frozen=True, slots=True)
class Usage:
    cpu_s: float
    peak_rss_kib: int


class _LagMonitor:
    """Async context manager measuring the worst event-loop stall inside it."""

    def __init__(self) -> None:
        self.worst_ms = NO_LAG_MS
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def _watch(self) -> None:
        worst = NO_LAG_MS
        while not self._stop.is_set():
            start = time.perf_counter()
            await asyncio.sleep(LAG_INTERVAL_S)
            worst = max(worst, time.perf_counter() - start - LAG_INTERVAL_S)
        self.worst_ms = worst * MS_PER_SECOND

    async def __aenter__(self) -> _LagMonitor:
        self._task = asyncio.create_task(self._watch())
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task


def _seconds(millis: float | None) -> float | None:
    return None if millis is None else millis / MS_PER_SECOND


def _build_run(url: str, round_no: int, outcome, wall: float, lag_ms: float) -> Run:
    media = outcome.media_files
    return Run(
        url=url,
        round=round_no,
        ok=outcome.success,
        wall_s=wall,
        extract_s=_seconds(outcome.timings.get("extract_ms")),
        fetch_s=_seconds(outcome.timings.get("fetch_ms")),
        files=len(media),
        videos=sum(1 for media_file in media if media_file.is_video),
        bytes=sum(media_file.path.stat().st_size for media_file in media),
        max_loop_lag_ms=lag_ms,
    )


async def run_once(url: str, round_no: int) -> Run:
    async with _LagMonitor() as monitor:
        started = time.perf_counter()
        outcome = await download_media(url)
        wall = time.perf_counter() - started
    run = _build_run(url, round_no, outcome, wall, monitor.worst_ms)
    if outcome.work_dir:
        cleanup(outcome.work_dir)
    return run


def _pct(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    pos = (len(ordered) - 1) * fraction
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _stat(runs: list[Run], attr: str) -> str:
    samples = [sample for run in runs if (sample := getattr(run, attr)) is not None]
    if not samples:
        return NOT_AVAILABLE
    median = statistics.median(samples)
    p95 = _pct(samples, P95)
    return f"{median:5.2f}/{p95:5.2f} "


def _first_line(cmd: list[str]) -> str:
    try:
        done = subprocess.run(
            cmd, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S, check=False
        )
    except OSError:
        return "missing"
    lines = (done.stdout or done.stderr).strip().splitlines()
    return lines[0] if lines else "missing"


def _versions() -> dict[str, str]:
    return {
        "commit": _first_line(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"]),
        "python": platform.python_version(),
        "gallery_dl": version("gallery-dl"),
        "ffmpeg": _first_line(["ffmpeg", "-version"]),
        "platform": platform.platform(),
        "cpus": str(os.cpu_count()),
    }


def _emit(text: str) -> None:
    print(text, flush=True)  # noqa: T201


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--pause", type=float, default=DEFAULT_PAUSE_S, help="seconds between batches"
    )
    parser.add_argument("--json", type=Path, help="write raw runs to this file")
    return parser.parse_args()


def _build_config(args: argparse.Namespace) -> dict[str, object]:
    return {
        "repeats": args.repeats,
        "concurrency": args.concurrency,
        "pause": args.pause,
        "cookies_file_present": Path(settings.COOKIES_FILE).is_file(),
        "instagram_login_configured": bool(settings.INSTAGRAM_USER and settings.INSTAGRAM_PASS),
        "download_timeout": settings.DOWNLOAD_TIMEOUT,
    }


def _print_run(run: Run) -> None:
    status = "ok " if run.ok else "ERR"
    size_mb = run.bytes / BYTES_PER_MB
    _emit(f"{status} {run.wall_s:6.2f}s files={run.files} {size_mb:6.2f}MB {run.url}")


async def _run_batch(batch: list[tuple[str, int]], pause: float | None) -> list[Run]:
    finished = await asyncio.gather(*(run_once(url, round_no) for url, round_no in batch))
    for run in finished:
        _print_run(run)
    if pause is not None:
        await asyncio.sleep(pause)
    return list(finished)


async def _run_all(args: argparse.Namespace, urls: list[str]) -> list[Run]:
    jobs = [(url, round_no) for round_no in range(args.repeats) for url in urls]
    size = args.concurrency
    batches = [jobs[start : start + size] for start in range(0, len(jobs), size)]
    runs: list[Run] = []
    for index, batch in enumerate(batches):
        pause = args.pause if index < len(batches) - 1 else None
        # batches must run in sequence, so await inside the loop is intended
        runs.extend(await _run_batch(batch, pause))
    return runs


def _cpu_seconds(before: resource.struct_rusage, after: resource.struct_rusage) -> float:
    return (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)


async def _benchmark(args: argparse.Namespace, urls: list[str]) -> tuple[list[Run], Usage]:
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    runs = await _run_all(args, urls)
    cpu_after = resource.getrusage(resource.RUSAGE_SELF)
    return runs, Usage(_cpu_seconds(cpu_before, cpu_after), cpu_after.ru_maxrss)


def _first_wall(good: list[Run]) -> str:
    first = next((run for run in good if run.round == 0), None)
    return "  n/a" if first is None else f"{first.wall_s:5.2f}"


def _summary_row(url: str, group: list[Run]) -> str:
    good = [run for run in group if run.ok]
    later = [run for run in good if run.round > 0]
    size_mb = statistics.median([run.bytes for run in good]) / BYTES_PER_MB if good else NO_LAG_MS
    url_cell = url[-URL_WIDTH:].ljust(URL_WIDTH)
    ok_cell = f"{len(good):>2}/{len(group):<2}"
    size_cell = f"{size_mb:6.2f}"
    files_cell = f"{good[0].files if good else 0:>5}"
    stats = "".join(_stat(later, attr) for attr in ("wall_s", "extract_s", "fetch_s"))
    return (
        f"{url_cell} {ok_cell} {size_cell} {files_cell}  {_first_wall(good)}"
        f"                  {stats}"
    )


def _print_summary(urls: list[str], runs: list[Run], usage: Usage) -> None:
    _emit(TABLE_HEADER)
    for url in urls:
        _emit(_summary_row(url, [run for run in runs if run.url == url]))
    worst_lag = max((run.max_loop_lag_ms for run in runs), default=NO_LAG_MS)
    lag_text = f"max event-loop lag: {worst_lag:.1f} ms; runs: {len(runs)}"
    cpu_text = f"process CPU: {usage.cpu_s:.2f} s"
    rss_text = f"peak RSS: {usage.peak_rss_kib / KIB_PER_MIB:.0f} MB"
    _emit(f"\n{lag_text}; {cpu_text}; {rss_text}")


def _write_json(path: Path, report: dict[str, object], runs: list[Run]) -> None:
    payload = {**report, "runs": [asdict(run) for run in runs]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))


async def main() -> int:
    args = _parse_args()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(LOG_LEVEL_ERROR))
    urls = [clean_url(raw_url.strip()) for raw_url in args.urls]
    report = {"versions": _versions(), "config": _build_config(args)}
    _emit(json.dumps(report, ensure_ascii=False))
    runs, usage = await _benchmark(args, urls)
    _print_summary(urls, runs, usage)
    if args.json:
        _write_json(args.json, report, runs)
    return 0 if all(run.ok for run in runs) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
