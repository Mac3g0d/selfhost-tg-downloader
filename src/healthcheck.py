import os
from pathlib import Path

import structlog

from config import settings

log = structlog.get_logger()


def run_healthchecks() -> None:
    log.info(
        "config_loaded",
        download_dir=settings.DOWNLOAD_DIR,
        download_timeout=settings.DOWNLOAD_TIMEOUT,
        cwd=os.getcwd(),
    )

    _check_auth()
    _check_inline()
    _check_database()
    _check_gallery_dl()
    _check_download_dir()


def _check_auth() -> None:
    has_creds = bool(settings.INSTAGRAM_USER and settings.INSTAGRAM_PASS)
    cookies_path = Path(settings.COOKIES_FILE)
    cookies_abs = cookies_path.resolve()
    has_cookies = cookies_path.is_file()

    if has_creds:
        log.info(
            "auth_method",
            method="credentials",
            instagram_user=settings.INSTAGRAM_USER,
        )
    elif has_cookies:
        size = cookies_abs.stat().st_size
        log.info(
            "auth_method",
            method="cookies",
            cookies_file=str(cookies_abs),
            file_size_bytes=size,
        )
    else:
        log.warning(
            "auth_missing",
            cookies_file_configured=settings.COOKIES_FILE,
            cookies_file_resolved=str(cookies_abs),
            cookies_file_exists=cookies_path.exists(),
            hint="Instagram downloads will fail without auth",
        )


def _check_inline() -> None:
    if settings.BUFFER_CHAT_ID:
        log.info("inline_mode", status="enabled", buffer_chat_id=settings.BUFFER_CHAT_ID)
    else:
        log.warning(
            "inline_mode",
            status="disabled",
            hint="Set BUFFER_CHAT_ID to enable inline mode",
        )


def _check_database() -> None:
    path = Path(settings.DATABASE_PATH)
    if path.exists():
        log.info("database_ok", path=str(path.resolve()))
    else:
        log.info("database_pending", path=str(path.resolve()), hint="Will be created on startup")


def _check_gallery_dl() -> None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        log.info("gallery_dl_found", version=version("gallery-dl"))
    except PackageNotFoundError:
        log.error("gallery_dl_missing", hint="Install the gallery-dl Python package")

    if settings.USE_ARIA2:
        log.warning("aria2_ignored", hint="gallery-dl has no aria2 support; USE_ARIA2 is unused")


def _check_download_dir() -> None:
    path = Path(settings.DOWNLOAD_DIR)
    if path.exists():
        log.info("download_dir_ok", path=str(path.resolve()))
    else:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.error("download_dir_failed", path=str(path))
        else:
            log.info("download_dir_created", path=str(path.resolve()))
