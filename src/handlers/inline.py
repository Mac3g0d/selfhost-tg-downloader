import hashlib
import random

import structlog
from aiogram import Bot, Router
from aiogram.types import (
    FSInputFile,
    InlineQuery,
    InlineQueryResult,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultsButton,
)

from config import settings
from downloader.gallery import DownloadResult, cleanup, download_media
from handlers.media import URL_PATTERN

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
        parts.append(f"📎 @{user.username}")

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

    log.info("inline_query", url=url, user_id=query.from_user.id)

    from database import get_cached_media, set_cached_media

    cached_data = await get_cached_media(url)
    if cached_data:
        log.info("inline_cache_hit", url=url)
        results: list[InlineQueryResult] = []
        for i, item in enumerate(cached_data):
            result_id = hashlib.md5(f"{url}:{i}".encode()).hexdigest()[:16]  # noqa: S324
            if item["type"] == "video":
                results.append(
                    InlineQueryResultCachedVideo(
                        id=result_id,
                        video_file_id=item["file_id"],
                        title=random.choice(TITLES),  # noqa: S311
                    )
                )
            else:
                results.append(
                    InlineQueryResultCachedPhoto(
                        id=result_id,
                        photo_file_id=item["file_id"],
                    )
                )
        await query.answer(results, cache_time=300)
        return

    # Отправляем "спиннер" пользователю в личку, чтобы было видно активность
    from aiogram.enums import ChatAction
    try:
        await bot.send_chat_action(chat_id=query.from_user.id, action=ChatAction.UPLOAD_VIDEO)
    except Exception:
        pass  # Может не сработать, если пользователь не жал /start

    result: DownloadResult = await download_media(url)

    if not result.success:
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
        results: list[InlineQueryResult] = []
        cache_items = []
        caption = _build_caption(query, url)

        for i, media_file in enumerate(result.media_files):
            input_file = FSInputFile(media_file.path)
            result_id = hashlib.md5(  # noqa: S324
                f"{url}:{i}".encode()
            ).hexdigest()[:16]

            if media_file.is_video:
                msg = await bot.send_video(
                    chat_id=settings.BUFFER_CHAT_ID,
                    video=input_file,
                    caption=caption,
                    supports_streaming=True,
                    disable_notification=True,
                )
                if msg.video:
                    file_id = msg.video.file_id
                    results.append(
                        InlineQueryResultCachedVideo(
                            id=result_id,
                            video_file_id=file_id,
                            title=random.choice(TITLES),  # noqa: S311
                        )
                    )
                    cache_items.append({"type": "video", "file_id": file_id})
            else:
                msg = await bot.send_photo(
                    chat_id=settings.BUFFER_CHAT_ID,
                    photo=input_file,
                    caption=caption,
                    disable_notification=True,
                )
                if msg.photo:
                    file_id = msg.photo[-1].file_id
                    results.append(
                        InlineQueryResultCachedPhoto(
                            id=result_id,
                            photo_file_id=file_id,
                        )
                    )
                    cache_items.append({"type": "photo", "file_id": file_id})

        if results:
            await set_cached_media(url, cache_items)
            await query.answer(results, cache_time=300)
            log.info("inline_answered", url=url, result_count=len(results))
        else:
            await query.answer([], cache_time=5)

    except Exception:
        log.exception("inline_failed", url=url)
        await query.answer([], cache_time=5)

    finally:
        if result.work_dir:
            cleanup(result.work_dir)
