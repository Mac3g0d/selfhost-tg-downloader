"""Download a URL (or reuse its cached file ids) and reply to the message with the media."""

import asyncio
import contextlib
from typing import Any

import structlog
from aiogram import Bot, exceptions
from aiogram.types import Message

import database
from constants import SEND_FAILED_TEXT, TEXT_DOWNLOADING, UPLOAD_ACTION
from downloader.gallery import DownloadResult, cleanup, download_media
from handlers.inline_ui import failure_text
from handlers.sending import reply_cached_item, send_all
from timing import StageTimer

log = structlog.get_logger()


async def deliver_url(message: Message, url: str, timer: StageTimer) -> None:
    user_id = message.from_user.id if message.from_user else "unknown"
    log.info("processing_url", url=url, user_id=user_id, chat_id=message.chat.id)

    with timer.stage("cache_lookup"):
        cached_data = await database.get_cached_media(url)
    if cached_data:
        await _reply_cached(message, url, timer, cached_data)
        return

    outcome, status_msg = await _download_with_status(message, url, timer)
    if not outcome.success:
        timings = timer.summary()
        log.info("message_timing", url=url, cache="miss", ok=False, **timings)
        await status_msg.edit_text(failure_text(outcome.error))
        return
    await _send_and_finish(message, url, timer, outcome, status_msg)


async def _reply_cached(
    message: Message, url: str, timer: StageTimer, cached_data: list[dict[str, Any]]
) -> None:
    log.info("inline_cache_hit", url=url)
    with timer.stage("send_cached"):
        for cached in cached_data:
            await reply_cached_item(message, cached)  # noqa: WPS476
    log.info("message_timing", url=url, cache="hit", **timer.summary())


async def _announce(message: Message, bot: Bot) -> Message:
    status = await message.reply(TEXT_DOWNLOADING)
    # The activity hint is optional: its failure must not cancel the delivery.
    with contextlib.suppress(exceptions.TelegramAPIError):
        await bot.send_chat_action(chat_id=message.chat.id, action=UPLOAD_ACTION)
    return status


async def _download_with_status(
    message: Message, url: str, timer: StageTimer
) -> tuple[DownloadResult, Message]:
    bot = message.bot
    if bot is None:
        raise RuntimeError("Message is not bound to a bot")

    # The status message must not delay the download: run both at once.
    with timer.stage("download"):
        outcome, announced = await asyncio.gather(
            download_media(url), _announce(message, bot), return_exceptions=True
        )
    if isinstance(outcome, BaseException):
        raise outcome
    if isinstance(announced, BaseException):
        if outcome.work_dir:
            cleanup(outcome.work_dir)
        raise announced
    return outcome, announced


async def _send_and_clear_status(
    message: Message,
    url: str,
    timer: StageTimer,
    outcome: DownloadResult,
    status_msg: Message,
) -> None:
    cache_items = await send_all(message, timer, outcome.media_files)
    if cache_items:
        with timer.stage("cache_write"):
            await database.set_cached_media(url, list(cache_items))
    with timer.stage("status"):
        await status_msg.delete()


def _finish(url: str, timer: StageTimer, outcome: DownloadResult) -> None:
    if outcome.work_dir:
        with timer.stage("cleanup"):
            cleanup(outcome.work_dir)
    log.info(
        "message_timing",
        url=url,
        cache="miss",
        file_count=len(outcome.media_files),
        **timer.summary(),
    )


async def _send_and_finish(
    message: Message,
    url: str,
    timer: StageTimer,
    outcome: DownloadResult,
    status_msg: Message,
) -> None:
    try:
        await _send_and_clear_status(message, url, timer, outcome, status_msg)
    except Exception:
        log.exception("send_media_failed", url=url)
        await status_msg.edit_text(SEND_FAILED_TEXT)
    finally:
        _finish(url, timer, outcome)
