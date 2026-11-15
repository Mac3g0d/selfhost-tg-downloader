"""Inline mode handlers.

One feature keeps its handlers and their small helpers together.
"""

# flake8: noqa: WPS202

import asyncio
import contextlib

import structlog
from aiogram import Bot, Router, enums, exceptions, types

from config import settings
from constants import (
    HIT_CACHE_SECONDS,
    KEY_FILE_ID,
    KEY_TYPE,
    MAX_ACTIVE_JOBS,
    NO_PREVIEW,
    NOOP_FILTER,
    PAGE_FILTER,
    PAGE_PREFIX,
    PLACEHOLDER_FILTER,
    PLACEHOLDER_PREFIX,
    REFRESH_FILTER,
    REFRESH_PREFIX,
    SHORT_CACHE_SECONDS,
    STATUS_TEMPLATE,
    TEXT_BUSY,
    TEXT_REFRESH,
    TEXT_RETRY,
    TEXT_UPLOADING,
    TYPE_PHOTO,
    TYPE_VIDEO,
    URL_PATTERN,
)
from database import get_cached_media, get_inline_link, save_inline_link, set_cached_media
from downloader.gallery import DownloadResult, MediaFile, cleanup, download_media
from handlers import inline_ui as ui
from inflight import url_lock
from timing import StageTimer, new_request_id
from utils import clean_url

log = structlog.get_logger()

router = Router(name="inline")


class DeliveryError(Exception):
    """Media could not be prepared; the message is safe to show to the user."""


class _Job:
    """One preparation of a URL: download, upload to the buffer chat, cache."""

    __slots__ = ("task", "timings", "uploading")

    def __init__(self) -> None:
        self.uploading = asyncio.Event()
        self.timings: dict[str, float] = {}
        self.task: asyncio.Task[ui.MediaEntries] | None = None


_jobs: dict[str, _Job] = {}
_delivering: set[str] = set()


def _supported_url(text: str) -> str:
    """The cleaned link from the query text, or an empty string if unsupported."""
    stripped = text.strip()
    cleaned = clean_url(stripped) if stripped else ""
    return cleaned if URL_PATTERN.match(cleaned.strip()) else ""


def _input_media(entry: dict[str, str]) -> types.InputMediaVideo | types.InputMediaPhoto:
    if entry[KEY_TYPE] == TYPE_VIDEO:
        return types.InputMediaVideo(media=entry[KEY_FILE_ID], supports_streaming=True)
    return types.InputMediaPhoto(media=entry[KEY_FILE_ID])


def _entry(kind: str, file_id: str) -> dict[str, str]:
    return {KEY_TYPE: kind, KEY_FILE_ID: file_id}


async def _send_media(bot: Bot, media_file: MediaFile, caption: str) -> dict[str, str] | None:
    """Upload one downloaded file to the buffer chat and return its cache entry."""
    input_file = types.FSInputFile(media_file.path)
    if media_file.is_video:
        sent = await bot.send_video(
            chat_id=settings.BUFFER_CHAT_ID,
            video=input_file,
            caption=caption,
            supports_streaming=True,
            disable_notification=True,
        )
        return _entry(TYPE_VIDEO, sent.video.file_id) if sent.video else None
    sent = await bot.send_photo(
        chat_id=settings.BUFFER_CHAT_ID,
        photo=input_file,
        caption=caption,
        disable_notification=True,
    )
    if not sent.photo:
        return None
    return _entry(TYPE_PHOTO, sent.photo[-1].file_id)


async def _upload_all(
    bot: Bot, downloaded: DownloadResult, caption: str, timer: StageTimer
) -> ui.MediaEntries:
    """Upload the files one at a time on purpose, so the buffer chat is not flooded."""
    uploaded: ui.MediaEntries = []
    for media_file in downloaded.media_files:
        with timer.stage("upload"):
            entry = await _send_media(bot, media_file, caption)  # noqa: WPS476
        if entry:
            uploaded.append(entry)
    return uploaded


async def _download_or_fail(url: str, timer: StageTimer) -> DownloadResult:
    with timer.stage("download"):
        downloaded = await download_media(url)
    if not downloaded.success:
        raise DeliveryError(downloaded.error or "не удалось скачать")
    return downloaded


async def _upload_downloaded(
    bot: Bot, downloaded: DownloadResult, url: str, caption: str, timer: StageTimer
) -> ui.MediaEntries:
    """Upload the downloaded files and always remove their work directory."""
    try:
        return await _upload_all(bot, downloaded, caption, timer)
    except Exception as exc:
        log.exception("inline_upload_failed", url=url)
        raise DeliveryError("ошибка при загрузке в Telegram") from exc
    finally:
        if downloaded.work_dir:
            cleanup(downloaded.work_dir)


async def _prepare_locked(
    job: _Job, bot: Bot, url: str, caption: str, timer: StageTimer
) -> ui.MediaEntries:
    with timer.stage("cache_lookup"):
        cached = await get_cached_media(url)
    if cached:
        return cached

    downloaded = await _download_or_fail(url, timer)
    job.uploading.set()
    uploaded = await _upload_downloaded(bot, downloaded, url, caption, timer)
    if not uploaded:
        raise DeliveryError("Telegram не принял файлы")

    with timer.stage("cache_write"):
        await set_cached_media(url, uploaded)
    return uploaded


def _log_job_timing(job: _Job, url: str, timer: StageTimer) -> None:
    job.timings.update(timer.summary())
    log.info("inline_job_timing", url=url, **job.timings)


async def _prepare(job: _Job, bot: Bot, url: str, caption: str) -> ui.MediaEntries:
    """Download the media, upload it to the buffer chat and cache the file ids."""
    timer = StageTimer()
    with structlog.contextvars.bound_contextvars(req_id=new_request_id()):
        async with contextlib.AsyncExitStack() as stack:
            stack.callback(_log_job_timing, job, url, timer)
            with timer.stage("queue"):
                await stack.enter_async_context(url_lock(url))
            return await _prepare_locked(job, bot, url, caption, timer)


def _on_job_done(url: str, done: asyncio.Task[ui.MediaEntries]) -> None:
    _jobs.pop(url, None)
    if done.cancelled():
        return
    error = done.exception()
    if error is not None:
        log.warning("inline_job_failed", url=url, error=str(error))


def _start_job(bot: Bot, url: str, caption: str) -> _Job:
    """Return the running preparation of this URL, starting one if needed.

    Preparations started by inline queries are not awaited by anyone until the
    placeholder is sent, so their number is capped.
    """
    running = _jobs.get(url)
    if running is not None:
        return running
    if len(_jobs) >= MAX_ACTIVE_JOBS:
        raise DeliveryError(TEXT_BUSY)

    job = _Job()
    _jobs[url] = job
    task = asyncio.create_task(_prepare(job, bot, url, caption))
    job.task = task
    task.add_done_callback(lambda done: _on_job_done(url, done))
    return job


async def _answer_button(query: types.InlineQuery, label: str, start_parameter: str) -> None:
    button = types.InlineQueryResultsButton(text=label, start_parameter=start_parameter)
    await query.answer([], cache_time=SHORT_CACHE_SECONDS, button=button)


async def _answer_cached(
    query: types.InlineQuery, url: str, cached: ui.MediaEntries, timer: StageTimer
) -> None:
    """Answer a cache hit.

    The link is saved here too, because the pager buttons look it up by this
    key, however it got cached.
    """
    key = ui.link_key(url)
    if len(cached) > 1:
        await save_inline_link(key, url)
    answers = ui.cached_results(key, url, cached)
    with timer.stage("answer"):
        await query.answer(answers, cache_time=HIT_CACHE_SECONDS)
    log.info("inline_timing", url=url, cache="hit", **timer.summary())


async def _show_activity(bot: Bot, user_id: int) -> None:
    with contextlib.suppress(Exception):
        await bot.send_chat_action(chat_id=user_id, action=enums.ChatAction.UPLOAD_VIDEO)


async def _answer_uncached(
    query: types.InlineQuery, placeholder: types.InlineQueryResultArticle
) -> None:
    """Answer with the placeholder.

    It is not cached by Telegram: the next query for this link must see the real media.
    """
    await query.answer([placeholder], cache_time=0, is_personal=True)


async def _answer_placeholder(
    query: types.InlineQuery, bot: Bot, url: str, timer: StageTimer
) -> None:
    key = ui.link_key(url)
    try:
        _start_job(bot, url, ui.build_caption(query.from_user, query.chat_type, url))
    except DeliveryError:
        log.warning("inline_busy", url=url, active_jobs=len(_jobs))
        await _answer_button(query, "⏳ Много загрузок, попробуй чуть позже", "busy")
        return
    await save_inline_link(key, url)

    placeholder = ui.placeholder_result(key, url)
    with timer.stage("answer"):
        await asyncio.gather(
            _answer_uncached(query, placeholder), _show_activity(bot, query.from_user.id)
        )
    log.info("inline_placeholder", url=url, **timer.summary())


@router.inline_query()
async def on_inline_query(query: types.InlineQuery, bot: Bot) -> None:
    url = _supported_url(query.query)
    if not url:
        await _answer_button(query, "Отправь ссылку TikTok / Instagram", "help")
        return

    if not settings.BUFFER_CHAT_ID:
        log.error("inline_no_buffer_chat", hint="Set BUFFER_CHAT_ID in .env")
        await _answer_button(query, "⚠️ Inline не настроен", "setup")
        return

    timer = StageTimer()
    log.info("inline_query", url=url, user_id=query.from_user.id)
    with timer.stage("cache_lookup"):
        cached = await get_cached_media(url)
    if cached:
        await _answer_cached(query, url, cached, timer)
        return
    await _answer_placeholder(query, bot, url, timer)


async def _edit_status(
    bot: Bot, inline_message_id: str, status: str, url: str, button: str
) -> None:
    """Show a status line; it is cosmetic, so its failure must not cancel the delivery."""
    try:
        await bot.edit_message_text(
            STATUS_TEMPLATE.format(status=status, url=url),
            inline_message_id=inline_message_id,
            link_preview_options=NO_PREVIEW,
            reply_markup=ui.refresh_keyboard(ui.link_key(url), button),
        )
    except exceptions.TelegramBadRequest:
        return
    except exceptions.TelegramAPIError as exc:
        log.warning("inline_status_failed", url=url, error=str(exc))


async def _remove_keyboard(bot: Bot, inline_message_id: str) -> None:
    with contextlib.suppress(exceptions.TelegramBadRequest):
        await bot.edit_message_reply_markup(inline_message_id=inline_message_id)


class _Delivery:
    """Replaces one sent placeholder with the media once it is ready."""

    def __init__(self, bot: Bot, inline_message_id: str, url: str) -> None:
        self.bot = bot
        self.inline_message_id = inline_message_id
        self.url = url
        self.timer = StageTimer()
        self.job: _Job | None = None

    async def run(self, user: types.User) -> bool:
        """Deliver the media, or show why it failed; tell whether it succeeded.

        On a flood limit or network trouble the media is cached, so the user
        can ask again with the button.
        """
        try:
            await self._deliver(user)
        except DeliveryError as exc:
            await _edit_status(
                self.bot,
                self.inline_message_id,
                ui.failure_text(str(exc)),
                self.url,
                TEXT_RETRY,
            )
            return False
        except exceptions.TelegramBadRequest as exc:
            log.warning("inline_edit_failed", url=self.url, error=str(exc))
            return False
        except exceptions.TelegramAPIError as exc:
            log.warning("inline_edit_failed", url=self.url, error=str(exc))
            await _edit_status(
                self.bot,
                self.inline_message_id,
                ui.failure_text("Telegram временно недоступен"),
                self.url,
                TEXT_RETRY,
            )
            return False
        return True

    async def _deliver(self, user: types.User) -> None:
        entries = await get_cached_media(self.url)
        if not entries:
            entries = await self._await_job(user)
        await self._show_media(entries)

    async def _await_job(self, user: types.User) -> ui.MediaEntries:
        caption = ui.build_caption(user, None, self.url)
        self.job = _start_job(self.bot, self.url, caption)
        task = self.job.task
        if task is None:
            raise DeliveryError("задача не запущена")
        uploading = asyncio.create_task(self.job.uploading.wait())
        with self.timer.stage("wait"), contextlib.ExitStack() as guard:
            guard.callback(uploading.cancel)
            await asyncio.wait({task, uploading}, return_when=asyncio.FIRST_COMPLETED)
            if not task.done():
                await _edit_status(
                    self.bot, self.inline_message_id, TEXT_UPLOADING, self.url, TEXT_REFRESH
                )
            return await asyncio.shield(task)

    async def _show_media(self, entries: ui.MediaEntries) -> None:
        markup = ui.pager(ui.link_key(self.url), 0, len(entries))
        with self.timer.stage("edit"):
            await self.bot.edit_message_media(
                _input_media(entries[0]),
                inline_message_id=self.inline_message_id,
                reply_markup=markup,
            )
            if markup is None:
                await _remove_keyboard(self.bot, self.inline_message_id)


def _log_delivery(delivery: _Delivery, succeeded: bool) -> None:
    job = delivery.job
    stages = {} if job is None else job.timings
    timings = {f"job_{stage}": ms for stage, ms in stages.items()}
    log.info(
        "inline_timing",
        url=delivery.url,
        cache="hit" if job is None else "miss",
        ok=succeeded,
        **timings,
        **delivery.timer.summary(),
    )


async def _deliver(bot: Bot, inline_message_id: str, url: str, user: types.User) -> None:
    """Replace a sent placeholder with the media once it is ready."""
    if inline_message_id in _delivering:
        return
    _delivering.add(inline_message_id)
    delivery = _Delivery(bot, inline_message_id, url)
    with contextlib.ExitStack() as guard:
        guard.callback(_delivering.discard, inline_message_id)
        succeeded = await delivery.run(user)
    _log_delivery(delivery, succeeded)


@router.chosen_inline_result(PLACEHOLDER_FILTER)
async def on_placeholder_sent(chosen: types.ChosenInlineResult, bot: Bot) -> None:
    if not chosen.inline_message_id:
        return
    url = await get_inline_link(chosen.result_id.removeprefix(PLACEHOLDER_PREFIX))
    if url:
        await _deliver(bot, chosen.inline_message_id, url, chosen.from_user)


@router.callback_query(REFRESH_FILTER)
async def on_refresh(callback: types.CallbackQuery, bot: Bot) -> None:
    url = await get_inline_link((callback.data or "").removeprefix(REFRESH_PREFIX))
    if not url or not callback.inline_message_id:
        await callback.answer("Ссылка устарела, отправь её заново", show_alert=True)
        return
    if callback.inline_message_id in _delivering:
        await callback.answer("Ещё готовлю, подожди немного")
        return
    await callback.answer("Проверяю…")
    await _deliver(bot, callback.inline_message_id, url, callback.from_user)


@router.callback_query(NOOP_FILTER)
async def on_page_counter(callback: types.CallbackQuery) -> None:
    await callback.answer()


async def _flip_page(
    bot: Bot, inline_message_id: str, key: str, entries: ui.MediaEntries, page: str
) -> None:
    index = int(page) % len(entries)
    with contextlib.suppress(exceptions.TelegramBadRequest):
        await bot.edit_message_media(
            _input_media(entries[index]),
            inline_message_id=inline_message_id,
            reply_markup=ui.pager(key, index, len(entries)),
        )


@router.callback_query(PAGE_FILTER)
async def on_page(callback: types.CallbackQuery, bot: Bot) -> None:
    payload = (callback.data or "").removeprefix(PAGE_PREFIX)
    key, _, page = payload.rpartition(":")
    url = await get_inline_link(key)
    entries = await get_cached_media(url) if url else None
    if not entries or not callback.inline_message_id or not page.isdigit():
        await callback.answer("Пост больше недоступен, отправь ссылку заново", show_alert=True)
        return
    await _flip_page(bot, callback.inline_message_id, key, entries, page)
    await callback.answer()
