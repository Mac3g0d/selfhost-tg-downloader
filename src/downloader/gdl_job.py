"""gallery-dl job class, one-time library setup and the blocking job runner."""

import logging
import threading
import time
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from gallery_dl import config as gdl_config
from gallery_dl import exception as gdl_exception
from gallery_dl import extractor as gdl_extractor
from gallery_dl.job import DownloadJob

from config import settings
from constants import CANCELLED_STATUS, INSTAGRAM_PATH, UNSUPPORTED_URL_STATUS, WORKER_PREFIX

FirstFileAt = float | None


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


class Job(DownloadJob):  # type: ignore[misc]
    """A gallery-dl download job bound to its own directory and cancel flag."""

    def __init__(
        self,
        extr: Any,
        parent: Job | None = None,
        *,
        dest: Path | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        super().__init__(extr, parent)
        self.dest: str = parent.dest if parent else str(dest)
        self.cancel: threading.Event = parent.cancel if parent else cancel or threading.Event()
        self.root: Job = parent.root if parent else self
        self.first_file_at: float | None = None

        # gallery-dl keeps its configuration in one process-wide store, so the
        # per-request destination is answered here instead of being written to it.
        self._shared_config = self.extractor.config
        self.extractor.config = self._answer_config

    @classmethod
    def execute(cls, url: str, dest: Path, cancel: threading.Event) -> tuple[int, FirstFileAt]:
        """Run a whole job; returns (gallery-dl status, time of the first file)."""
        job = cls(url, dest=dest, cancel=cancel)
        return int(job.run()), job.first_file_at

    def handle_url(self, url: str, kwdict: dict[str, Any]) -> None:
        self._check_cancelled()
        if self.root.first_file_at is None:
            self.root.first_file_at = time.perf_counter()
        super().handle_url(url, kwdict)

    def handle_queue(self, url: str, kwdict: dict[str, Any]) -> None:
        self._check_cancelled()
        super().handle_queue(url, kwdict)

    def _answer_config(self, key: str, default: Any = None) -> Any:
        if key == "base-directory":
            return self.dest
        return self._shared_config(key, default)

    def _check_cancelled(self) -> None:
        if self.cancel.is_set():
            raise gdl_exception.TerminateExtraction()


class _Setup:
    """One-time, thread-safe preparation of the gallery-dl library."""

    def __init__(self) -> None:
        self._setup_lock = threading.Lock()
        self._find_lock = threading.Lock()
        self._ready = False
        self._find: Any = None

    def ensure(self) -> None:
        with self._setup_lock:
            if self._ready:
                return
            gdl_config.load()
            self._hide_worker_logs()
            self._set_instagram_defaults()
            self._lock_extractor_lookup()
            self._ready = True

    def _hide_worker_logs(self) -> None:
        root = logging.getLogger()
        for sink in root.handlers:
            sink.addFilter(_HideWorkerLogs())
        root.addHandler(ERRORS)

    def _set_instagram_defaults(self) -> None:
        # gallery-dl spaces Instagram requests 6-12 s apart within one process.
        # Every download used to be a fresh process, which never waited; keep
        # that behaviour unless the user's own gallery-dl config says otherwise.
        if gdl_config.get(INSTAGRAM_PATH, "sleep-request") is None:
            gdl_config.set(INSTAGRAM_PATH, "sleep-request", 0)

        # Without yt-dlp gallery-dl first fails to open the DASH manifest and
        # then falls back to the plain video URL; ask for that URL directly.
        has_ytdl = find_spec("yt_dlp") is not None or find_spec("youtube_dl") is not None
        if not has_ytdl and gdl_config.get(INSTAGRAM_PATH, "videos") is None:
            gdl_config.set(INSTAGRAM_PATH, "videos", "merged")

    def _lock_extractor_lookup(self) -> None:
        # Extractor lookup lazily imports modules through one shared generator,
        # which must not be advanced from two worker threads at once.
        self._find = gdl_extractor.find
        gdl_extractor.find = self._locked_find  # ty: ignore[invalid-assignment]

    def _locked_find(self, url: str) -> Any:
        with self._find_lock:
            return self._find(url)


ERRORS = _ErrorCollector()
_SETUP = _Setup()


def apply_settings() -> None:
    gdl_config.set((), "mtime", False)
    gdl_config.set(("output",), "mode", "null")

    if settings.INSTAGRAM_USER and settings.INSTAGRAM_PASS:
        gdl_config.set(INSTAGRAM_PATH, "username", settings.INSTAGRAM_USER)
        gdl_config.set(INSTAGRAM_PATH, "password", settings.INSTAGRAM_PASS)
        gdl_config.unset((), "cookies")
    else:
        gdl_config.unset(INSTAGRAM_PATH, "username")
        gdl_config.unset(INSTAGRAM_PATH, "password")
        if settings.COOKIES_FILE and Path(settings.COOKIES_FILE).is_file():
            gdl_config.set((), "cookies", settings.COOKIES_FILE)
        else:
            gdl_config.unset((), "cookies")


def run_job(url: str, work_dir: Path, cancel: threading.Event) -> tuple[int, str, FirstFileAt]:
    """Blocking gallery-dl run; returns (status, error text, time of first file)."""
    if cancel.is_set():
        # Timed out while waiting for a free worker: do not contact the site at all.
        return CANCELLED_STATUS, "Download cancelled", None
    _SETUP.ensure()
    apply_settings()
    ERRORS.start()
    try:
        status, first_file_at = Job.execute(url, work_dir, cancel)
    except gdl_exception.NoExtractorError:
        return UNSUPPORTED_URL_STATUS, "Unsupported URL", None
    except gdl_exception.TerminateExtraction:
        return CANCELLED_STATUS, "Download cancelled", None
    finally:
        errors = ERRORS.finish()
    return status, errors, first_file_at
