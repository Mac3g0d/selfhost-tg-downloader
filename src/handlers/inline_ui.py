"""Texts, keyboards and result builders of the inline mode."""

import hashlib
import html
import secrets
from typing import Any

from aiogram import types

import constants

MediaEntries = list[dict[str, Any]]


def link_key(url: str) -> str:
    """Short stable key under which a link is stored for callbacks."""
    return hashlib.sha256(url.encode()).hexdigest()[: constants.LINK_KEY_LENGTH]


def build_caption(user: types.User, chat_type: str | None, url: str) -> str:
    """Caption of the file uploaded to the buffer chat."""
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


def failure_text(reason: str) -> str:
    """Status shown in place of the media when it could not be prepared."""
    escaped = html.escape(reason[: constants.ERROR_TEXT_LIMIT])
    return f"❌ Не удалось скачать:\n<code>{escaped}</code>"


def refresh_keyboard(key: str, text: str = constants.TEXT_REFRESH) -> types.InlineKeyboardMarkup:
    button = types.InlineKeyboardButton(text=text, callback_data=constants.REFRESH_PREFIX + key)
    return types.InlineKeyboardMarkup(inline_keyboard=[[button]])


def pager(key: str, index: int, total: int) -> types.InlineKeyboardMarkup | None:
    """Buttons to flip through a multi-file post inside one message.

    An inline message holds a single media and cannot become an album, so the
    other files are reached by replacing the media in place.
    """
    if total < 2:
        return None
    previous_index = (index - 1) % total
    next_index = (index + 1) % total
    page_number = index + 1
    row = [
        types.InlineKeyboardButton(
            text="◀️", callback_data=f"{constants.PAGE_PREFIX}{key}:{previous_index}"
        ),
        types.InlineKeyboardButton(
            text=f"{page_number} / {total}", callback_data=constants.PAGE_NOOP
        ),
        types.InlineKeyboardButton(
            text="▶️", callback_data=f"{constants.PAGE_PREFIX}{key}:{next_index}"
        ),
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=[row])


def placeholder_result(key: str, url: str) -> types.InlineQueryResultArticle:
    """Article that is sent at once and later replaced by the media.

    Telegram drops an inline answer that arrives later than roughly 8-10 seconds
    after the query (measured on a live bot), so a cache miss is answered at once
    with a placeholder message that is replaced by the media when it is ready.
    """
    text = constants.STATUS_TEMPLATE.format(status=constants.TEXT_DOWNLOADING, url=url)
    return types.InlineQueryResultArticle(
        id=constants.PLACEHOLDER_PREFIX + key,
        title="⏳ Отправить — медиа появится в сообщении",
        input_message_content=types.InputTextMessageContent(
            message_text=text, link_preview_options=constants.NO_PREVIEW
        ),
        reply_markup=refresh_keyboard(key),
    )


def cached_results(
    key: str, url: str, entries: MediaEntries
) -> list[types.InlineQueryResultUnion]:
    """Answers that point at already uploaded files."""
    built: list[types.InlineQueryResultUnion] = []
    for index, entry in enumerate(entries):
        digest = hashlib.sha256(f"{url}:{index}".encode())
        result_id = digest.hexdigest()[: constants.RESULT_ID_LENGTH]
        if entry[constants.KEY_TYPE] == constants.TYPE_VIDEO:
            built.append(
                types.InlineQueryResultCachedVideo(
                    id=result_id,
                    video_file_id=entry[constants.KEY_FILE_ID],
                    title=secrets.choice(constants.TITLES),
                    reply_markup=pager(key, index, len(entries)),
                )
            )
        else:
            built.append(
                types.InlineQueryResultCachedPhoto(
                    id=result_id,
                    photo_file_id=entry[constants.KEY_FILE_ID],
                    reply_markup=pager(key, index, len(entries)),
                )
            )
    return built
