import asyncio
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import structlog
from gallery_dl import config as gdl_config
from gallery_dl import exception as gdl_exception
from gallery_dl import extractor as gdl_extractor
from gallery_dl.job import DownloadJob

from config import settings

log = structlog.get_logger()

VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi"})
IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})
MAX_PARALLEL_DOWNLOADS = 8
WORKER_PREFIX = "gallery-dl"


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


class _ErrorCollector(logging.Handler):
    """Collects gallery-dl error messages per worker thread."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._by_thread: dict[int, list[str]] = {}

    def start(self) -> None:
        self._by_thread[threading.get_ident()] = []

    def finish(self) -> str:
        return "\n".join(self._by_thread.pop(threading.get_ident(), []))

    def emit(self, record: logging.LogRecord) -> None:
        messages = self._by_thread.get(record.thread or 0)
        if messages is not None:
            messages.append(f"[{record.name}][error] {record.getMessage()}")


class _HideWorkerLogs(logging.Filter):
    """Keeps gallery-dl's own chatter out of the bot log, as when it was a subprocess.

    Its errors are still collected and reported once per failed download.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.threadName or "").startswith(WORKER_PREFIX)


class _Job(DownloadJob):  # type: ignore[misc]
    """A gallery-dl download job bound to its own directory and cancel flag."""

    def __init__(
        self,
        extr: Any,
        parent: _Job | None = None,
        *,
        dest: Path | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        super().__init__(extr, parent)
        self.dest: str = parent.dest if parent else str(dest)
        self.cancel: threading.Event = parent.cancel if parent else cancel or threading.Event()
        self.root: _Job = parent.root if parent else self
        self.first_file_at: float | None = None

        # gallery-dl keeps its configuration in one process-wide store, so the
        # per-request destination is answered here instead of being written to it.
        lookup = self.extractor.config

        def config(key: str, default: Any = None) -> Any:
            if key == "base-directory":
                return self.dest
            return lookup(key, default)

        self.extractor.config = config

    def _check_cancelled(self) -> None:
        if self.cancel.is_set():
            raise gdl_exception.TerminateExtraction()

    def handle_url(self, url: str, kwdict: dict[str, Any]) -> None:
        self._check_cancelled()
        if self.root.first_file_at is None:
            self.root.first_file_at = time.perf_counter()
        super().handle_url(url, kwdict)

    def handle_queue(self, url: str, kwdict: dict[str, Any]) -> None:
        self._check_cancelled()
        super().handle_queue(url, kwdict)


_executor = ThreadPoolExecutor(
    max_workers=MAX_PARALLEL_DOWNLOADS, thread_name_prefix=WORKER_PREFIX
)
_errors = _ErrorCollector()
_setup_lock = threading.Lock()
_find_lock = threading.Lock()
_ready = False


def _setup_once() -> None:
    global _ready
    with _setup_lock:
        if _ready:
            return
        gdl_config.load()
        root = logging.getLogger()
        for handler in root.handlers:
            handler.addFilter(_HideWorkerLogs())
        root.addHandler(_errors)

        # gallery-dl spaces Instagram requests 6-12 s apart within one process.
        # Every download used to be a fresh process, which never waited; keep
        # that behaviour unless the user's own gallery-dl config says otherwise.
        instagram = ("extractor", "instagram")
        if gdl_config.get(instagram, "sleep-request") is None:
            gdl_config.set(instagram, "sleep-request", 0)

        # Without yt-dlp gallery-dl first fails to open the DASH manifest and
        # then falls back to the plain video URL; ask for that URL directly.
        has_ytdl = find_spec("yt_dlp") is not None or find_spec("youtube_dl") is not None
        if not has_ytdl and gdl_config.get(instagram, "videos") is None:
            gdl_config.set(instagram, "videos", "merged")

        # Extractor lookup lazily imports modules through one shared generator,
        # which must not be advanced from two worker threads at once.
        find = gdl_extractor.find

        def locked_find(url: str) -> Any:
            with _find_lock:
                return find(url)

        gdl_extractor.find = locked_find  # ty: ignore[invalid-assignment]
        _ready = True


def _apply_settings() -> None:
    gdl_config.set((), "mtime", False)
    gdl_config.set(("output",), "mode", "null")

    instagram = ("extractor", "instagram")
    if settings.INSTAGRAM_USER and settings.INSTAGRAM_PASS:
        gdl_config.set(instagram, "username", settings.INSTAGRAM_USER)
        gdl_config.set(instagram, "password", settings.INSTAGRAM_PASS)
        gdl_config.unset((), "cookies")
    else:
        gdl_config.unset(instagram, "username")
        gdl_config.unset(instagram, "password")
        if settings.COOKIES_FILE and Path(settings.COOKIES_FILE).is_file():
            gdl_config.set((), "cookies", settings.COOKIES_FILE)
        else:
            gdl_config.unset((), "cookies")


def _run_job(url: str, work_dir: Path, cancel: threading.Event) -> tuple[int, str, float | None]:
    """Blocking gallery-dl run; returns (status, error text, time of first file)."""
    _setup_once()
    _apply_settings()
    _errors.start()
    job: _Job | None = None
    try:
        job = _Job(url, dest=work_dir, cancel=cancel)
        status = int(job.run())
    except gdl_exception.NoExtractorError:
        return 64, "Unsupported URL", None
    except gdl_exception.TerminateExtraction:
        return 1, "Download cancelled", None
    finally:
        errors = _errors.finish()
    return status, errors, job.first_file_at


async def download_media(url: str) -> DownloadResult:
    os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
    work_dir = Path(
        tempfile.mkdtemp(dir=settings.DOWNLOAD_DIR, prefix=f"dl-{uuid.uuid4().hex[:8]}-")
    )

    log.info("starting_download", url=url)
    started = time.perf_counter()
    cancel = threading.Event()
    future = asyncio.get_running_loop().run_in_executor(_executor, _run_job, url, work_dir, cancel)

    try:
        status, errors, first_file_at = await asyncio.wait_for(
            asyncio.shield(future), timeout=settings.DOWNLOAD_TIMEOUT
        )
    except TimeoutError:
        log.error("download_timeout", url=url, timeout=settings.DOWNLOAD_TIMEOUT)
        # A thread cannot be killed: ask the job to stop at its next step and
        # remove its directory only once it has really finished writing.
        cancel.set()
        future.add_done_callback(lambda _: cleanup(work_dir))
        return DownloadResult(
            success=False, error=f"Download timed out ({settings.DOWNLOAD_TIMEOUT}s)"
        )
    except Exception:
        log.exception("gallery_dl_crashed", url=url)
        cleanup(work_dir)
        return DownloadResult(success=False, error="gallery-dl failed unexpectedly")

    finished = time.perf_counter()
    media_files = _collect_media(work_dir)

    if status != 0:
        log.error("gallery_dl_failed", status=status, stderr=errors)
        cleanup(work_dir)
        return DownloadResult(success=False, error=errors or "gallery-dl exited with error")

    if not media_files:
        log.warning("no_media_files", url=url)
        cleanup(work_dir)
        return DownloadResult(success=False, error="No media files found after download")

    timings = {"download_ms": round((finished - started) * 1000, 1)}
    if first_file_at is not None:
        timings["extract_ms"] = round((first_file_at - started) * 1000, 1)
        timings["fetch_ms"] = round((finished - first_file_at) * 1000, 1)

    log.info(
        "download_complete",
        url=url,
        file_count=len(media_files),
        total_bytes=sum(item.path.stat().st_size for item in media_files),
        status=status,
        work_dir=str(work_dir),
        **timings,
    )
    return DownloadResult(
        success=True, media_files=media_files, work_dir=work_dir, timings=timings
    )


def cleanup(directory: Path) -> None:
    try:
        shutil.rmtree(directory, ignore_errors=True)
        log.debug("cleanup_done", directory=str(directory))
    except Exception:
        log.exception("cleanup_failed", directory=str(directory))
