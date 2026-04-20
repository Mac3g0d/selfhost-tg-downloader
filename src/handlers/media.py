import re

import structlog
from aiogram import Router, types
from aiogram.enums import ChatAction
from aiogram.types import FSInputFile

from config import settings
from downloader.gallery import DownloadResult, cleanup, download_media

log = structlog.get_logger()

router = Router(name="media")

URL_PATTERN: re.Pattern[str] = re.compile(
    r"https?://(?:"
    r"(?:www\.|vm\.|vt\.)?tiktok\.com"
    r"|(?:www\.)?instagram\.com"
    r"|(?:www\.)?instagr\.am"
    r")/\S+",
    re.IGNORECASE,
)


def _extract_urls(text: str) -> list[str]:
    from utils import clean_url
    return [clean_url(u) for u in URL_PATTERN.findall(text)]


async def _process_url(message: types.Message, url: str) -> None:
    user_id = message.from_user.id if message.from_user else "unknown"
    log.info("processing_url", url=url, user_id=user_id, chat_id=message.chat.id)

    from database import get_cached_media, set_cached_media

    cached_data = await get_cached_media(url)
    if cached_data:
        log.info("inline_cache_hit", url=url)
        for item in cached_data:
            if item["type"] == "video":
                await message.reply_video(video=item["file_id"], supports_streaming=True)
            else:
                await message.reply_photo(photo=item["file_id"])
        return

    status_msg = await message.reply("⏳ Скачиваю...")

    await message.bot.send_chat_action(  # type: ignore[union-attr]
        chat_id=message.chat.id,
        action=ChatAction.UPLOAD_VIDEO,
    )

    result: DownloadResult = await download_media(url)

    if not result.success:
        await status_msg.edit_text(f"❌ Не удалось скачать:\n<code>{result.error}</code>")
        return

    try:
        cache_items = []
        for media_file in result.media_files:
            file_path = media_file.path
            file_size = file_path.stat().st_size

            if file_size > settings.max_telegram_file_size:
                await message.reply(
                    f"⚠️ Файл слишком большой ({file_size / 1024 / 1024:.1f} MB). "
                    f"Лимит Telegram — {settings.max_telegram_file_size / 1024 / 1024:.0f} MB."
                )
                continue

            input_file = FSInputFile(file_path)

            if media_file.is_video:
                msg = await message.reply_video(video=input_file, supports_streaming=True)
                if msg.video:
                    cache_items.append({"type": "video", "file_id": msg.video.file_id})
            else:
                msg = await message.reply_photo(photo=input_file)
                if msg.photo:
                    cache_items.append({"type": "photo", "file_id": msg.photo[-1].file_id})

        if cache_items:
            await set_cached_media(url, cache_items)

        await status_msg.delete()

    except Exception:
        log.exception("send_media_failed", url=url)
        await status_msg.edit_text("❌ Ошибка при отправке файла в Telegram.")

    finally:
        if result.work_dir:
            cleanup(result.work_dir)


@router.message()
async def on_message(message: types.Message) -> None:
    if not message.text:
        return

    urls = _extract_urls(message.text)
    if not urls:
        return

    for url in urls:
        await _process_url(message, url)
