import re
from contextlib import AsyncExitStack

import structlog
from aiogram import Router, types
from aiogram.enums import ChatAction
from aiogram.types import FSInputFile

from config import settings
from downloader.gallery import DownloadResult, cleanup, download_media
from inflight import url_lock
from timing import StageTimer, new_request_id

log = structlog.get_logger()

router = Router(name="media")

URL_PATTERN: re.Pattern[str] = re.compile(
    r"https?://(?:"
    r"(?:www\.|vm\.|vt\.|p\.|m\.)?tiktok\.com"
    r"|(?:www\.)?instagram\.com"
    r"|(?:www\.)?instagr\.am"
    r")/[\w\-./?%&=+@]*",
    re.IGNORECASE,
)


def _extract_urls(text: str) -> list[str]:
    from utils import clean_url

    return [clean_url(u.strip()) for u in URL_PATTERN.findall(text)]


async def _process_url(message: types.Message, url: str) -> None:
    timer = StageTimer()
    with structlog.contextvars.bound_contextvars(req_id=new_request_id()):
        async with AsyncExitStack() as stack:
            with timer.stage("queue"):
                await stack.enter_async_context(url_lock(url))
            await _deliver_url(message, url, timer)


async def _deliver_url(message: types.Message, url: str, timer: StageTimer) -> None:
    user_id = message.from_user.id if message.from_user else "unknown"
    log.info("processing_url", url=url, user_id=user_id, chat_id=message.chat.id)

    from database import get_cached_media, set_cached_media

    with timer.stage("cache_lookup"):
        cached_data = await get_cached_media(url)
    if cached_data:
        log.info("inline_cache_hit", url=url)
        with timer.stage("send_cached"):
            for item in cached_data:
                if item["type"] == "video":
                    await message.reply_video(video=item["file_id"], supports_streaming=True)
                else:
                    await message.reply_photo(photo=item["file_id"])
        log.info("message_timing", url=url, cache="hit", **timer.summary())
        return

    bot = message.bot
    if bot is None:
        raise RuntimeError("Message is not bound to a bot")

    with timer.stage("status"):
        status_msg = await message.reply("⏳ Скачиваю...")

        await bot.send_chat_action(
            chat_id=message.chat.id,
            action=ChatAction.UPLOAD_VIDEO,
        )

    with timer.stage("download"):
        result: DownloadResult = await download_media(url)

    if not result.success:
        log.info("message_timing", url=url, cache="miss", ok=False, **timer.summary())
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
                with timer.stage("upload"):
                    msg = await message.reply_video(video=input_file, supports_streaming=True)
                if msg.video:
                    cache_items.append({"type": "video", "file_id": msg.video.file_id})
            else:
                with timer.stage("upload"):
                    msg = await message.reply_photo(photo=input_file)
                if msg.photo:
                    cache_items.append({"type": "photo", "file_id": msg.photo[-1].file_id})

        if cache_items:
            with timer.stage("cache_write"):
                await set_cached_media(url, cache_items)

        with timer.stage("status"):
            await status_msg.delete()

    except Exception:
        log.exception("send_media_failed", url=url)
        await status_msg.edit_text("❌ Ошибка при отправке файла в Telegram.")

    finally:
        if result.work_dir:
            with timer.stage("cleanup"):
                cleanup(result.work_dir)
        log.info(
            "message_timing",
            url=url,
            cache="miss",
            file_count=len(result.media_files),
            **timer.summary(),
        )


@router.message()
async def on_message(message: types.Message) -> None:
    if not message.text:
        return

    urls = _extract_urls(message.text)
    if not urls:
        return

    for url in urls:
        await _process_url(message, url)
