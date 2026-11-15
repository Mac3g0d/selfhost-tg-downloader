"""Send downloaded or cached media files to a Telegram chat."""

from typing import Any

from aiogram.types import FSInputFile, Message

from config import settings
from downloader.gallery import MediaFile
from timing import StageTimer

FILE_ID = "file_id"
_VIDEO = "video"
_PHOTO = "photo"
_BYTES_PER_MB = 1024 * 1024

CacheItem = dict[str, str]


async def reply_cached_item(message: Message, cached: dict[str, Any]) -> None:
    if cached["type"] == _VIDEO:
        await message.reply_video(video=cached[FILE_ID], supports_streaming=True)
    else:
        await message.reply_photo(photo=cached[FILE_ID])


def _too_large_text(file_size: int) -> str:
    size_mb = file_size / _BYTES_PER_MB
    limit_mb = settings.max_telegram_file_size / _BYTES_PER_MB
    return f"⚠️ Файл слишком большой ({size_mb:.1f} MB). Лимит Telegram — {limit_mb:.0f} MB."


def _cache_item(sent: Message, *, is_video: bool) -> CacheItem | None:
    if is_video and sent.video:
        return {"type": _VIDEO, FILE_ID: sent.video.file_id}
    if not is_video and sent.photo:
        return {"type": _PHOTO, FILE_ID: sent.photo[-1].file_id}
    return None


async def _send_file(
    message: Message, timer: StageTimer, media_file: MediaFile
) -> CacheItem | None:
    file_size = media_file.path.stat().st_size
    if file_size > settings.max_telegram_file_size:
        await message.reply(_too_large_text(file_size))
        return None

    input_file = FSInputFile(media_file.path)
    with timer.stage("upload"):
        if media_file.is_video:
            sent = await message.reply_video(video=input_file, supports_streaming=True)
        else:
            sent = await message.reply_photo(photo=input_file)
    return _cache_item(sent, is_video=media_file.is_video)


async def send_all(
    message: Message, timer: StageTimer, media_files: list[MediaFile]
) -> list[CacheItem]:
    cache_items: list[CacheItem] = []
    for media_file in media_files:
        # Sequential on purpose: keeps the album order and avoids Telegram flood limits.
        cache_item = await _send_file(message, timer, media_file)  # noqa: WPS476
        if cache_item:
            cache_items.append(cache_item)
    return cache_items
