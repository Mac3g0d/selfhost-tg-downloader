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
        gallery_dl_bin=settings.gallery_dl_bin,
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
    import shutil

    binary = shutil.which(settings.gallery_dl_bin)
    if binary:
        log.info("gallery_dl_found", path=binary)
    else:
        log.error("gallery_dl_missing", configured_bin=settings.gallery_dl_bin)

    if settings.USE_ARIA2:
        aria_bin = shutil.which("aria2c")
        if aria_bin:
            log.info("aria2c_found", path=aria_bin)
        else:
            log.warning("aria2c_missing", hint="Install aria2c to speed up downloads")


def _check_download_dir() -> None:
    path = Path(settings.DOWNLOAD_DIR)
    if path.exists():
        log.info("download_dir_ok", path=str(path.resolve()))
    else:
        try:
            path.mkdir(parents=True, exist_ok=True)
            log.info("download_dir_created", path=str(path.resolve()))
        except OSError:
            log.error("download_dir_failed", path=str(path))
