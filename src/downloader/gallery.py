import asyncio
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from config import settings

log = structlog.get_logger()

VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi"})
IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})


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


def _build_gallery_dl_config(work_dir: Path) -> Path | None:
    if not (settings.INSTAGRAM_USER and settings.INSTAGRAM_PASS):
        return None

    config = {
        "extractor": {
            "instagram": {
                "username": settings.INSTAGRAM_USER,
                "password": settings.INSTAGRAM_PASS,
            }
        }
    }

    config_path = work_dir / "gallery-dl.json"
    config_path.write_text(json.dumps(config))
    return config_path


def _build_cmd(work_dir: Path) -> list[str]:
    cmd: list[str] = [
        settings.gallery_dl_bin,
        "--no-mtime",
        "--dest",
        str(work_dir),
    ]

    config_path = _build_gallery_dl_config(work_dir)
    if config_path:
        cmd.extend(["--config", str(config_path)])
    elif settings.COOKIES_FILE and Path(settings.COOKIES_FILE).is_file():
        cmd.extend(["--cookies", settings.COOKIES_FILE])

    if settings.USE_ARIA2:
        cmd.extend(["--downloader", "aria2"])

    # Speed up yt-dlp (used by gallery-dl for many sites)
    cmd.extend([
        "--option", f"ytdl.concurrent-fragments={settings.CONCURRENT_FRAGMENTS}",
    ])

    return cmd


async def download_media(url: str) -> DownloadResult:
    os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
    work_dir = Path(
        tempfile.mkdtemp(dir=settings.DOWNLOAD_DIR, prefix=f"dl-{uuid.uuid4().hex[:8]}-")
    )

    cmd = _build_cmd(work_dir)
    cmd.extend(["--", url])

    log.info("starting_download", url=url, cmd=" ".join(cmd))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=settings.DOWNLOAD_TIMEOUT,
        )

        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            log.error("gallery_dl_failed", returncode=proc.returncode, stderr=err_msg)
            cleanup(work_dir)
            return DownloadResult(success=False, error=err_msg or "gallery-dl exited with error")

        log.debug("gallery_dl_stdout", output=stdout.decode(errors="replace").strip())

    except TimeoutError:
        log.error("download_timeout", url=url, timeout=settings.DOWNLOAD_TIMEOUT)
        proc.kill()
        cleanup(work_dir)
        return DownloadResult(
            success=False, error=f"Download timed out ({settings.DOWNLOAD_TIMEOUT}s)"
        )

    except FileNotFoundError:
        log.error("gallery_dl_not_found", binary=settings.gallery_dl_bin)
        cleanup(work_dir)
        return DownloadResult(success=False, error="gallery-dl is not installed or not in PATH")

    media_files = _collect_media(work_dir)
    if not media_files:
        log.warning("no_media_files", url=url)
        cleanup(work_dir)
        return DownloadResult(success=False, error="No media files found after download")

    log.info("download_complete", url=url, file_count=len(media_files), work_dir=str(work_dir))
    return DownloadResult(success=True, media_files=media_files, work_dir=work_dir)


def cleanup(directory: Path) -> None:
    try:
        shutil.rmtree(directory, ignore_errors=True)
        log.debug("cleanup_done", directory=str(directory))
    except Exception:
        log.exception("cleanup_failed", directory=str(directory))

