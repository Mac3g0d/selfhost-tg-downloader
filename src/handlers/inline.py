import asyncio
import contextlib
import hashlib
import html
import secrets
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import structlog
from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultsButton,
    InlineQueryResultUnion,
    InputMediaPhoto,
    InputMediaVideo,
    InputTextMessageContent,
    LinkPreviewOptions,
    User,
)

from config import settings
from database import get_cached_media, get_inline_link, save_inline_link, set_cached_media
from downloader.gallery import cleanup, download_media
from handlers.media import URL_PATTERN
from inflight import url_lock
from timing import StageTimer, new_request_id

log = structlog.get_logger()

router = Router(name="inline")

# Telegram drops an inline answer that arrives later than roughly 8-10 seconds
# after the query (measured on a live bot), so a cache miss is answered at once
# with a placeholder message that is replaced by the media when it is ready.
PLACEHOLDER_PREFIX = "w:"
REFRESH_PREFIX = "r:"
PAGE_PREFIX = "g:"
PAGE_NOOP = "g:-"
TEXT_DOWNLOADING = "⏳ Скачиваю…"
TEXT_UPLOADING = "⬆️ Загружаю в Telegram…"
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


TITLES: list[str] = [
    "очень крутое видео",
    "это точно понравится твоей маме",
    "ты серьезно хочешь это прислать?",
    "когда ты последний раз звонил маме?",
    "ты сегодня пил воду?",
    "что вершит судьбу человечества в этом мире?",
    "сон — это репетиция смерти.",
    "ты — лишь набор атомов, смотрящий в экран.",
    "траффик уходит, время не вернешь.",
    "это видео изменит твою жизнь (нет).",
    "опять деградируем?",
    "нажми, если осмелишься.",
    "вселенная бесконечна, а этот видос — нет.",
    "ты уверен, что это не симуляция?",
    "однажды нас всех забудут.",
    "просто нажми и не думай.",
    "А ты покакал сегодня?",
    "Два лучше, чем один.",
    "Чем морщинистей изюм, тем он слаще.",
    "Старина, съеби нахуй.",
    "Если упал, вставай, если встал, упай. Чокопай.",
    "Че губу раскатал?",
    "Любишь кататься- люби и катайся.",
    "Много хочешь- мало получишь.",
]


class DeliveryError(Exception):
    """Media could not be prepared; the message is safe to show to the user."""


@dataclass(slots=True, eq=False)
class _Job:
    """One preparation of a URL: download, upload to the buffer chat, cache."""

    uploading: asyncio.Event = field(default_factory=asyncio.Event)
    timings: dict[str, float] = field(default_factory=dict)
    task: asyncio.Task[list[dict[str, Any]]] | None = None


_jobs: dict[str, _Job] = {}
_delivering: set[str] = set()


def _is_supported_url(text: str) -> bool:
    return bool(URL_PATTERN.match(text.strip()))


def _link_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def _build_caption(user: User, chat_type: str | None, url: str) -> str:
    parts = [
        f"👤 <b>{html.escape(user.full_name)}</b>",
        f"🆔 <code>{user.id}</code>",
    ]

    if user.username:
        parts.append(f"📎 {user.username}")

    if chat_type:
        parts.append(f"💬 {chat_type}")

    parts.append(f"🔗 {url}")

    return "\n".join(parts)


def _refresh_keyboard(key: str, text: str = "🔄 Обновить") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=REFRESH_PREFIX + key)]]
    )


def _pager(key: str, index: int, total: int) -> InlineKeyboardMarkup | None:
    """Buttons to flip through a multi-file post inside one message.

    An inline message holds a single media and cannot become an album, so the
    other files are reached by replacing the media in place.
    """
    if total < 2:
        return None
    previous_page = f"{PAGE_PREFIX}{key}:{(index - 1) % total}"
    next_page = f"{PAGE_PREFIX}{key}:{(index + 1) % total}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◀️", callback_data=previous_page),
                InlineKeyboardButton(text=f"{index + 1} / {total}", callback_data=PAGE_NOOP),
                InlineKeyboardButton(text="▶️", callback_data=next_page),
            ]
        ]
    )


def _input_media(item: dict[str, Any]) -> InputMediaVideo | InputMediaPhoto:
    if item["type"] == "video":
        return InputMediaVideo(media=item["file_id"], supports_streaming=True)
    return InputMediaPhoto(media=item["file_id"])


def _status_text(status: str, url: str) -> str:
    return f"{status}\n🔗 {url}"


def _cached_results(url: str, items: list[dict[str, Any]]) -> list[InlineQueryResultUnion]:
    key = _link_key(url)
    results: list[InlineQueryResultUnion] = []
    for i, item in enumerate(items):
        result_id = hashlib.sha256(f"{url}:{i}".encode()).hexdigest()[:16]
        pager = _pager(key, i, len(items))
        if item["type"] == "video":
            results.append(
                InlineQueryResultCachedVideo(
                    id=result_id,
                    video_file_id=item["file_id"],
                    title=secrets.choice(TITLES),
                    reply_markup=pager,
                )
            )
        else:
            results.append(
                InlineQueryResultCachedPhoto(
                    id=result_id, photo_file_id=item["file_id"], reply_markup=pager
                )
            )
    return results


async def _prepare(job: _Job, bot: Bot, url: str, caption: str) -> list[dict[str, Any]]:
    """Download the media, upload it to the buffer chat and cache the file ids."""
    timer = StageTimer()
    with structlog.contextvars.bound_contextvars(req_id=new_request_id()):
        try:
            async with AsyncExitStack() as stack:
                with timer.stage("queue"):
                    await stack.enter_async_context(url_lock(url))
                return await _prepare_locked(job, bot, url, caption, timer)
        finally:
            job.timings.update(timer.summary())
            log.info("inline_job_timing", url=url, **job.timings)


async def _prepare_locked(
    job: _Job, bot: Bot, url: str, caption: str, timer: StageTimer
) -> list[dict[str, Any]]:
    with timer.stage("cache_lookup"):
        cached = await get_cached_media(url)
    if cached:
        return cached

    with timer.stage("download"):
        result = await download_media(url)
    if not result.success:
        raise DeliveryError(result.error or "не удалось скачать")

    job.uploading.set()
    try:
        items: list[dict[str, Any]] = []
        for media_file in result.media_files:
            input_file = FSInputFile(media_file.path)
            with timer.stage("upload"):
                if media_file.is_video:
                    msg = await bot.send_video(
                        chat_id=settings.BUFFER_CHAT_ID,
                        video=input_file,
                        caption=caption,
                        supports_streaming=True,
                        disable_notification=True,
                    )
                    if msg.video:
                        items.append({"type": "video", "file_id": msg.video.file_id})
                else:
                    msg = await bot.send_photo(
                        chat_id=settings.BUFFER_CHAT_ID,
                        photo=input_file,
                        caption=caption,
                        disable_notification=True,
                    )
                    if msg.photo:
                        items.append({"type": "photo", "file_id": msg.photo[-1].file_id})
    except Exception as exc:
        log.exception("inline_upload_failed", url=url)
        raise DeliveryError("ошибка при загрузке в Telegram") from exc
    finally:
        if result.work_dir:
            cleanup(result.work_dir)

    if not items:
        raise DeliveryError("Telegram не принял файлы")

    with timer.stage("cache_write"):
        await set_cached_media(url, items)
    return items


def _start_job(bot: Bot, url: str, caption: str) -> _Job:
    """Return the running preparation of this URL, starting one if needed."""
    job = _jobs.get(url)
    if job is not None:
        return job

    job = _jobs[url] = _Job()
    task = job.task = asyncio.create_task(_prepare(job, bot, url, caption))

    def finished(done: asyncio.Task[list[dict[str, Any]]]) -> None:
        _jobs.pop(url, None)
        if not done.cancelled() and (error := done.exception()) is not None:
            log.warning("inline_job_failed", url=url, error=str(error))

    task.add_done_callback(finished)
    return job


@router.inline_query()
async def on_inline_query(query: InlineQuery, bot: Bot) -> None:
    from utils import clean_url

    url = clean_url(query.query.strip()) if query.query.strip() else ""

    if not url or not _is_supported_url(url):
        await query.answer(
            [],
            cache_time=5,
            button=InlineQueryResultsButton(
                text="Отправь ссылку TikTok / Instagram",
                start_parameter="help",
            ),
        )
        return

    if not settings.BUFFER_CHAT_ID:
        log.error("inline_no_buffer_chat", hint="Set BUFFER_CHAT_ID in .env")
        await query.answer(
            [],
            cache_time=5,
            button=InlineQueryResultsButton(
                text="⚠️ Inline не настроен",
                start_parameter="setup",
            ),
        )
        return

    timer = StageTimer()
    log.info("inline_query", url=url, user_id=query.from_user.id)

    with timer.stage("cache_lookup"):
        cached = await get_cached_media(url)
    if cached:
        with timer.stage("answer"):
            await query.answer(_cached_results(url, cached), cache_time=300)
        log.info("inline_timing", url=url, cache="hit", **timer.summary())
        return

    key = _link_key(url)
    await save_inline_link(key, url)
    _start_job(bot, url, _build_caption(query.from_user, query.chat_type, url))

    async def show_activity() -> None:
        with contextlib.suppress(Exception):
            await bot.send_chat_action(chat_id=query.from_user.id, action=ChatAction.UPLOAD_VIDEO)

    placeholder = InlineQueryResultArticle(
        id=PLACEHOLDER_PREFIX + key,
        title="⏳ Отправить — медиа появится в сообщении",
        input_message_content=InputTextMessageContent(
            message_text=_status_text(TEXT_DOWNLOADING, url),
            link_preview_options=NO_PREVIEW,
        ),
        reply_markup=_refresh_keyboard(key),
    )

    async def answer() -> None:
        # Not cached by Telegram: the next query for this link must see the real media.
        await query.answer([placeholder], cache_time=0, is_personal=True)

    with timer.stage("answer"):
        await asyncio.gather(answer(), show_activity())
    log.info("inline_placeholder", url=url, **timer.summary())


async def _edit_status(bot: Bot, inline_message_id: str, text: str, key: str, button: str) -> None:
    with contextlib.suppress(TelegramBadRequest):
        await bot.edit_message_text(
            text,
            inline_message_id=inline_message_id,
            link_preview_options=NO_PREVIEW,
            reply_markup=_refresh_keyboard(key, button),
        )


async def _deliver(bot: Bot, inline_message_id: str, url: str, user: User) -> None:
    """Replace a sent placeholder with the media once it is ready."""
    if inline_message_id in _delivering:
        return
    _delivering.add(inline_message_id)
    timer = StageTimer()
    key = _link_key(url)
    job: _Job | None = None
    try:
        items = await get_cached_media(url)
        if not items:
            job = _start_job(bot, url, _build_caption(user, None, url))
            if job.task is None:
                raise DeliveryError("задача не запущена")
            with timer.stage("wait"):
                uploading = asyncio.create_task(job.uploading.wait())
                try:
                    await asyncio.wait({job.task, uploading}, return_when=asyncio.FIRST_COMPLETED)
                    if not job.task.done():
                        await _edit_status(
                            bot,
                            inline_message_id,
                            _status_text(TEXT_UPLOADING, url),
                            key,
                            "🔄 Обновить",
                        )
                    items = await asyncio.shield(job.task)
                finally:
                    uploading.cancel()

        pager = _pager(key, 0, len(items))
        with timer.stage("edit"):
            await bot.edit_message_media(
                _input_media(items[0]), inline_message_id=inline_message_id, reply_markup=pager
            )
            if pager is None:
                with contextlib.suppress(TelegramBadRequest):
                    await bot.edit_message_reply_markup(inline_message_id=inline_message_id)
        ok = True
    except DeliveryError as exc:
        ok = False
        reason = html.escape(str(exc)[:300])
        await _edit_status(
            bot,
            inline_message_id,
            _status_text(f"❌ Не удалось скачать:\n<code>{reason}</code>", url),
            key,
            "🔁 Повторить",
        )
    except TelegramBadRequest as exc:
        ok = False
        log.warning("inline_edit_failed", url=url, error=str(exc))
    finally:
        _delivering.discard(inline_message_id)

    job_timings = {f"job_{name}": value for name, value in (job.timings if job else {}).items()}
    log.info(
        "inline_timing",
        url=url,
        cache="miss" if job else "hit",
        ok=ok,
        **job_timings,
        **timer.summary(),
    )


@router.chosen_inline_result(F.result_id.startswith(PLACEHOLDER_PREFIX))
async def on_placeholder_sent(chosen: ChosenInlineResult, bot: Bot) -> None:
    if not chosen.inline_message_id:
        return
    url = await get_inline_link(chosen.result_id.removeprefix(PLACEHOLDER_PREFIX))
    if url:
        await _deliver(bot, chosen.inline_message_id, url, chosen.from_user)


@router.callback_query(F.data.startswith(REFRESH_PREFIX))
async def on_refresh(callback: CallbackQuery, bot: Bot) -> None:
    url = await get_inline_link((callback.data or "").removeprefix(REFRESH_PREFIX))
    if not url or not callback.inline_message_id:
        await callback.answer("Ссылка устарела, отправь её заново", show_alert=True)
        return
    if callback.inline_message_id in _delivering:
        await callback.answer("Ещё готовлю, подожди немного")
        return
    await callback.answer("Проверяю…")
    await _deliver(bot, callback.inline_message_id, url, callback.from_user)


@router.callback_query(F.data == PAGE_NOOP)
async def on_page_counter(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith(PAGE_PREFIX))
async def on_page(callback: CallbackQuery, bot: Bot) -> None:
    key, _, page = (callback.data or "").removeprefix(PAGE_PREFIX).rpartition(":")
    url = await get_inline_link(key)
    items = await get_cached_media(url) if url else None
    if not items or not callback.inline_message_id or not page.isdigit():
        await callback.answer("Пост больше недоступен, отправь ссылку заново", show_alert=True)
        return

    index = int(page) % len(items)
    with contextlib.suppress(TelegramBadRequest):
        await bot.edit_message_media(
            _input_media(items[index]),
            inline_message_id=callback.inline_message_id,
            reply_markup=_pager(key, index, len(items)),
        )
    await callback.answer()
