import asyncio
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from config import settings
from downloader.gdl_job import WORKER_PREFIX, Job, apply_settings, run_job

log = structlog.get_logger()

VIDEO_EXTENSIONS: frozenset[str] = frozenset((".mp4", ".mov", ".mkv", ".webm", ".avi"))
IMAGE_EXTENSIONS: frozenset[str] = frozenset((".jpg", ".jpeg", ".png", ".webp"))
MAX_PARALLEL_DOWNLOADS = 8
DIR_ID_LENGTH = 8
MS_PER_SECOND = 1000


@dataclass(frozen=True, slots=True)
class MediaFile:
    path: Path
    is_video: bool


@dataclass(slots=True)
class DownloadResult:
    success: bool
    media_files: list[MediaFile] = field(default_factory=list)
    error: str = ""
    work_dir: Path | None = None
    timings: dict[str, float] = field(default_factory=dict)


def _collect_media(directory: Path) -> list[MediaFile]:
    files: list[MediaFile] = []
    for entry in sorted(directory.rglob("*")):
        if not entry.is_file():
            continue
        suffix = entry.suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            files.append(MediaFile(path=entry, is_video=True))
        elif suffix in IMAGE_EXTENSIONS:
            files.append(MediaFile(path=entry, is_video=False))
    return files


# Names other modules and the tests import (and patch) from here.
_Job = Job
_apply_settings = apply_settings
_run_job = run_job

_executor = ThreadPoolExecutor(
    max_workers=MAX_PARALLEL_DOWNLOADS, thread_name_prefix=WORKER_PREFIX
)


class _Download:
    """One download request: its work directory, timing and outcome."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.cancel = threading.Event()
        Path(settings.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
        short_id = uuid.uuid4().hex[:DIR_ID_LENGTH]
        prefix = f"dl-{short_id}-"
        self.work_dir = Path(tempfile.mkdtemp(dir=settings.DOWNLOAD_DIR, prefix=prefix))
        self._started = time.perf_counter()

    async def run(self) -> DownloadResult:
        log.info("starting_download", url=self.url)
        future = asyncio.get_running_loop().run_in_executor(
            _executor, _run_job, self.url, self.work_dir, self.cancel
        )
        try:
            status, errors, first_file_at = await asyncio.wait_for(
                asyncio.shield(future), timeout=settings.DOWNLOAD_TIMEOUT
            )
        except TimeoutError:
            return self._timed_out(future)
        except Exception:
            return self._crashed()
        return self._finish(status, errors, first_file_at)

    def _timed_out(self, future: asyncio.Future[tuple[int, str, float | None]]) -> DownloadResult:
        log.error("download_timeout", url=self.url, timeout=settings.DOWNLOAD_TIMEOUT)
        # A thread cannot be killed: ask the job to stop at its next step and
        # remove its directory only once it has really finished writing.
        self.cancel.set()
        future.add_done_callback(lambda _: cleanup(self.work_dir))
        return DownloadResult(
            success=False, error=f"Download timed out ({settings.DOWNLOAD_TIMEOUT}s)"
        )

    def _crashed(self) -> DownloadResult:
        log.exception("gallery_dl_crashed", url=self.url)
        return self._fail("gallery-dl failed unexpectedly")

    def _finish(self, status: int, errors: str, first_file_at: float | None) -> DownloadResult:
        finished = time.perf_counter()
        media_files = _collect_media(self.work_dir)

        if status != 0:
            log.error("gallery_dl_failed", status=status, stderr=errors)
            return self._fail(errors or "gallery-dl exited with error")

        if not media_files:
            log.warning("no_media_files", url=self.url)
            return self._fail("No media files found after download")

        timings = self._timings(finished, first_file_at)
        log.info(
            "download_complete",
            url=self.url,
            file_count=len(media_files),
            total_bytes=sum(media.path.stat().st_size for media in media_files),
            status=status,
            work_dir=str(self.work_dir),
            **timings,
        )
        return DownloadResult(
            success=True, media_files=media_files, work_dir=self.work_dir, timings=timings
        )

    def _timings(self, finished: float, first_file_at: float | None) -> dict[str, float]:
        timings = {"download_ms": round((finished - self._started) * MS_PER_SECOND, 1)}
        if first_file_at is not None:
            timings["extract_ms"] = round((first_file_at - self._started) * MS_PER_SECOND, 1)
            timings["fetch_ms"] = round((finished - first_file_at) * MS_PER_SECOND, 1)
        return timings

    def _fail(self, error: str) -> DownloadResult:
        cleanup(self.work_dir)
        return DownloadResult(success=False, error=error)


async def download_media(url: str) -> DownloadResult:
    return await _Download(url).run()


def cleanup(directory: Path) -> None:
    try:
        shutil.rmtree(directory, ignore_errors=True)
    except Exception:
        log.exception("cleanup_failed", directory=str(directory))
    else:
        log.debug("cleanup_done", directory=str(directory))
