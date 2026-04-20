import hashlib

import structlog
from aiogram import Bot, Router
from aiogram.types import (
    FSInputFile,
    InlineQuery,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultsButton,
)

from config import settings
from downloader.gallery import DownloadResult, cleanup, download_media
from handlers.media import URL_PATTERN

log = structlog.get_logger()

router = Router(name="inline")


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
    url = query.query.strip()

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
        results = []
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
                    results.append(
                        InlineQueryResultCachedVideo(
                            id=result_id,
                            video_file_id=msg.video.file_id,
                            title=f"Video {i + 1}",
                        )
                    )
            else:
                msg = await bot.send_photo(
                    chat_id=settings.BUFFER_CHAT_ID,
                    photo=input_file,
                    caption=caption,
                    disable_notification=True,
                )
                if msg.photo:
                    results.append(
                        InlineQueryResultCachedPhoto(
                            id=result_id,
                            photo_file_id=msg.photo[-1].file_id,
                        )
                    )

        await query.answer(results, cache_time=300)
        log.info("inline_answered", url=url, result_count=len(results))

    except Exception:
        log.exception("inline_failed", url=url)
        await query.answer([], cache_time=5)

    finally:
        if result.work_dir:
            cleanup(result.work_dir)
