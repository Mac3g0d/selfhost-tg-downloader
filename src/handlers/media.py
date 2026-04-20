import re
from pathlib import Path

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
    return URL_PATTERN.findall(text)


async def _send_media_file(
    message: types.Message,
    file_path: Path,
    *,
    is_video: bool,
) -> None:
    file_size = file_path.stat().st_size

    if file_size > settings.max_telegram_file_size:
        await message.reply(
            f"⚠️ Файл слишком большой ({file_size / 1024 / 1024:.1f} MB). "
            f"Лимит Telegram — {settings.max_telegram_file_size / 1024 / 1024:.0f} MB."
        )
        return

    input_file = FSInputFile(file_path)

    if is_video:
        await message.reply_video(video=input_file, supports_streaming=True)
    else:
        await message.reply_photo(photo=input_file)


async def _process_url(message: types.Message, url: str) -> None:
    user_id = message.from_user.id if message.from_user else "unknown"
    log.info("processing_url", url=url, user_id=user_id, chat_id=message.chat.id)

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
        for media_file in result.media_files:
            await _send_media_file(message, media_file.path, is_video=media_file.is_video)

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
