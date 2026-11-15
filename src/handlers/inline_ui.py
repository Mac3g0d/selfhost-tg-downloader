"""Texts, keyboards and result builders of the inline mode."""

import hashlib
import html
import secrets
from typing import Any

from aiogram import F as EVENT_FILTER
from aiogram import types

MediaEntries = list[dict[str, Any]]

# Telegram drops an inline answer that arrives later than roughly 8-10 seconds
# after the query (measured on a live bot), so a cache miss is answered at once
# with a placeholder message that is replaced by the media when it is ready.
PLACEHOLDER_PREFIX = "w:"
REFRESH_PREFIX = "r:"
PAGE_PREFIX = "g:"
PAGE_NOOP = "g:-"

PLACEHOLDER_FILTER = EVENT_FILTER.result_id.startswith(PLACEHOLDER_PREFIX)
REFRESH_FILTER = EVENT_FILTER.data.startswith(REFRESH_PREFIX)
NOOP_FILTER = EVENT_FILTER.data == PAGE_NOOP
PAGE_FILTER = EVENT_FILTER.data.startswith(PAGE_PREFIX)

TEXT_DOWNLOADING = "⏳ Голова, терпани малеха, качаю"
TEXT_UPLOADING = "⬆️ Загружаю в Telegram…"
TEXT_REFRESH = "🔄 Обновить"
TEXT_RETRY = "🔁 Повторить"
STATUS_TEMPLATE = "{status}\n🔗 {url}"
NO_PREVIEW = types.LinkPreviewOptions(is_disabled=True)

KEY_TYPE = "type"
KEY_FILE_ID = "file_id"
TYPE_VIDEO = "video"
TYPE_PHOTO = "photo"

LINK_KEY_LENGTH = 24
RESULT_ID_LENGTH = 16
ERROR_TEXT_LIMIT = 300

TITLES: tuple[str, ...] = (
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
)


def link_key(url: str) -> str:
    """Short stable key under which a link is stored for callbacks."""
    return hashlib.sha256(url.encode()).hexdigest()[:LINK_KEY_LENGTH]


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
    escaped = html.escape(reason[:ERROR_TEXT_LIMIT])
    return f"❌ Не удалось скачать:\n<code>{escaped}</code>"


def refresh_keyboard(key: str, text: str = TEXT_REFRESH) -> types.InlineKeyboardMarkup:
    button = types.InlineKeyboardButton(text=text, callback_data=REFRESH_PREFIX + key)
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
        types.InlineKeyboardButton(text="◀️", callback_data=f"{PAGE_PREFIX}{key}:{previous_index}"),
        types.InlineKeyboardButton(text=f"{page_number} / {total}", callback_data=PAGE_NOOP),
        types.InlineKeyboardButton(text="▶️", callback_data=f"{PAGE_PREFIX}{key}:{next_index}"),
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=[row])


def placeholder_result(key: str, url: str) -> types.InlineQueryResultArticle:
    """Article that is sent at once and later replaced by the media."""
    text = STATUS_TEMPLATE.format(status=TEXT_DOWNLOADING, url=url)
    return types.InlineQueryResultArticle(
        id=PLACEHOLDER_PREFIX + key,
        title="⏳ Отправить — медиа появится в сообщении",
        input_message_content=types.InputTextMessageContent(
            message_text=text, link_preview_options=NO_PREVIEW
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
        result_id = digest.hexdigest()[:RESULT_ID_LENGTH]
        if entry[KEY_TYPE] == TYPE_VIDEO:
            built.append(
                types.InlineQueryResultCachedVideo(
                    id=result_id,
                    video_file_id=entry[KEY_FILE_ID],
                    title=secrets.choice(TITLES),
                    reply_markup=pager(key, index, len(entries)),
                )
            )
        else:
            built.append(
                types.InlineQueryResultCachedPhoto(
                    id=result_id,
                    photo_file_id=entry[KEY_FILE_ID],
                    reply_markup=pager(key, index, len(entries)),
                )
            )
    return built
