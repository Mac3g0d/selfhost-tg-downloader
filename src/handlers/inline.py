import asyncio
import contextlib
import hashlib
import secrets
from contextlib import AsyncExitStack

import structlog
from aiogram import Bot, Router
from aiogram.enums import ChatAction
from aiogram.types import (
    FSInputFile,
    InlineQuery,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultsButton,
    InlineQueryResultUnion,
)

from config import settings
from downloader.gallery import DownloadResult, cleanup, download_media
from handlers.media import URL_PATTERN
from inflight import url_lock
from timing import StageTimer, new_request_id

log = structlog.get_logger()

router = Router(name="inline")


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


def _is_supported_url(text: str) -> bool:
    return bool(URL_PATTERN.match(text.strip()))


def _build_caption(query: InlineQuery, url: str) -> str:
    user = query.from_user
    parts = [
        f"👤 <b>{user.full_name}</b>",
        f"🆔 <code>{user.id}</code>",
    ]

    if user.username:
        parts.append(f"📎 {user.username}")

    if query.chat_type:
        parts.append(f"💬 {query.chat_type}")

    parts.append(f"🔗 {url}")

    return "\n".join(parts)


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
    with structlog.contextvars.bound_contextvars(req_id=new_request_id()):
        async with AsyncExitStack() as stack:
            with timer.stage("queue"):
                await stack.enter_async_context(url_lock(url))
            await _answer_supported_url(query, bot, url, timer)


async def _answer_supported_url(query: InlineQuery, bot: Bot, url: str, timer: StageTimer) -> None:
    log.info("inline_query", url=url, user_id=query.from_user.id)

    from database import get_cached_media, set_cached_media

    with timer.stage("cache_lookup"):
        cached_data = await get_cached_media(url)
    if cached_data:
        log.info("inline_cache_hit", url=url)
        results: list[InlineQueryResultUnion] = []
        for i, item in enumerate(cached_data):
            result_id = hashlib.sha256(f"{url}:{i}".encode()).hexdigest()[:16]
            if item["type"] == "video":
                results.append(
                    InlineQueryResultCachedVideo(
                        id=result_id,
                        video_file_id=item["file_id"],
                        title=secrets.choice(TITLES),
                    )
                )
            else:
                results.append(
                    InlineQueryResultCachedPhoto(
                        id=result_id,
                        photo_file_id=item["file_id"],
                    )
                )
        with timer.stage("answer"):
            await query.answer(results, cache_time=300)
        log.info("inline_timing", url=url, cache="hit", **timer.summary())
        return

    # Отправляем "спиннер" пользователю в личку, чтобы было видно активность

    async def show_activity() -> None:
        with contextlib.suppress(Exception):
            await bot.send_chat_action(chat_id=query.from_user.id, action=ChatAction.UPLOAD_VIDEO)

    # The activity hint must not delay the download: run both at once.
    result: DownloadResult
    with timer.stage("download"):
        result, _ = await asyncio.gather(download_media(url), show_activity())

    if not result.success:
        log.info("inline_timing", url=url, cache="miss", ok=False, **timer.summary())
        await query.answer(
            [],
            cache_time=5,
            button=InlineQueryResultsButton(
                text=f"❌ {result.error[:40]}",
                start_parameter="error",
            ),
        )
        return

    try:
        uploaded_results: list[InlineQueryResultUnion] = []
        cache_items = []
        caption = _build_caption(query, url)

        for i, media_file in enumerate(result.media_files):
            input_file = FSInputFile(media_file.path)
            result_id = hashlib.sha256(f"{url}:{i}".encode()).hexdigest()[:16]

            if media_file.is_video:
                with timer.stage("upload"):
                    msg = await bot.send_video(
                        chat_id=settings.BUFFER_CHAT_ID,
                        video=input_file,
                        caption=caption,
                        supports_streaming=True,
                        disable_notification=True,
                    )
                if msg.video:
                    file_id = msg.video.file_id
                    uploaded_results.append(
                        InlineQueryResultCachedVideo(
                            id=result_id,
                            video_file_id=file_id,
                            title=secrets.choice(TITLES),
                        )
                    )
                    cache_items.append({"type": "video", "file_id": file_id})
            else:
                with timer.stage("upload"):
                    msg = await bot.send_photo(
                        chat_id=settings.BUFFER_CHAT_ID,
                        photo=input_file,
                        caption=caption,
                        disable_notification=True,
                    )
                if msg.photo:
                    file_id = msg.photo[-1].file_id
                    uploaded_results.append(
                        InlineQueryResultCachedPhoto(
                            id=result_id,
                            photo_file_id=file_id,
                        )
                    )
                    cache_items.append({"type": "photo", "file_id": file_id})

        if uploaded_results:
            with timer.stage("cache_write"):
                await set_cached_media(url, cache_items)
            with timer.stage("answer"):
                await query.answer(uploaded_results, cache_time=300)
            log.info("inline_answered", url=url, result_count=len(uploaded_results))
        else:
            await query.answer([], cache_time=5)

    except Exception:
        log.exception("inline_failed", url=url)
        await query.answer([], cache_time=5)

    finally:
        if result.work_dir:
            with timer.stage("cleanup"):
                cleanup(result.work_dir)
        log.info(
            "inline_timing",
            url=url,
            cache="miss",
            file_count=len(result.media_files),
            **timer.summary(),
        )
