"""Constants shared by the bot modules."""

import re
from typing import Final

from aiogram import F as EVENT_FILTER
from aiogram import types
from aiogram.utils.magic_filter import MagicFilter

MS_PER_SECOND: Final = 1000
BYTES_PER_MB: Final = 1024 * 1024

TELEGRAM_LIMIT_MB: Final = 50
TELEGRAM_FILE_LIMIT: Final = TELEGRAM_LIMIT_MB * 1024 * 1024

WORKER_PREFIX: Final = "gallery-dl"
UNSUPPORTED_URL_STATUS: Final = 64
CANCELLED_STATUS: Final = 1
INSTAGRAM_PATH: Final[tuple[str, ...]] = ("extractor", "instagram")

VIDEO_EXTENSIONS: Final[frozenset[str]] = frozenset((".mp4", ".mov", ".mkv", ".webm", ".avi"))
IMAGE_EXTENSIONS: Final[frozenset[str]] = frozenset((".jpg", ".jpeg", ".png", ".webp"))
MAX_PARALLEL_DOWNLOADS: Final = 8
WORK_DIR_PREFIX: Final = "dl-"

URL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"https?://(?:"
    r"(?:www\.|vm\.|vt\.|p\.|m\.)?tiktok\.com"
    r"|(?:www\.)?instagram\.com"
    r"|(?:www\.)?instagr\.am"
    r")/[\w\-./?%&=+@]*",
    re.IGNORECASE,
)

KEY_TYPE: Final = "type"
KEY_FILE_ID: Final = "file_id"
TYPE_VIDEO: Final = "video"
TYPE_PHOTO: Final = "photo"

UPLOAD_ACTION: Final = "upload_video"
SEND_FAILED_TEXT: Final = "❌ Ошибка при отправке файла в Telegram."

WELCOME_TEXT: Final = (
    "👋 <b>Привет!</b>\n\n"
    "Я скачиваю видео из <b>TikTok</b> и <b>Instagram</b>.\n\n"
    "Просто отправь мне ссылку — я скачаю и пришлю видео прямо сюда.\n\n"
    "🔗 <b>Поддерживаемые ссылки:</b>\n"
    "• <code>tiktok.com</code> / <code>vm.tiktok.com</code>\n"
    "• <code>instagram.com/reel/...</code>\n"
    "• <code>instagram.com/p/...</code>"
)

SHORT_CACHE_SECONDS: Final = 5
HIT_CACHE_SECONDS: Final = 300
MAX_ACTIVE_JOBS: Final = 16
TEXT_BUSY: Final = "слишком много загрузок, попробуй чуть позже"

PLACEHOLDER_PREFIX: Final = "w:"
REFRESH_PREFIX: Final = "r:"
PAGE_PREFIX: Final = "g:"
PAGE_NOOP: Final = "g:-"

PLACEHOLDER_FILTER: Final[MagicFilter] = EVENT_FILTER.result_id.startswith(PLACEHOLDER_PREFIX)
REFRESH_FILTER: Final[MagicFilter] = EVENT_FILTER.data.startswith(REFRESH_PREFIX)
NOOP_FILTER: Final[MagicFilter] = EVENT_FILTER.data == PAGE_NOOP
PAGE_FILTER: Final[MagicFilter] = EVENT_FILTER.data.startswith(PAGE_PREFIX)

TEXT_DOWNLOADING: Final = "⏳ Голова, терпани малеха, качаю"
TEXT_UPLOADING: Final = "⬆️ Загружаю в Telegram…"
TEXT_REFRESH: Final = "🔄 Обновить"
TEXT_RETRY: Final = "🔁 Повторить"
STATUS_TEMPLATE: Final = "{status}\n🔗 {url}"
NO_PREVIEW: Final[types.LinkPreviewOptions] = types.LinkPreviewOptions(is_disabled=True)

LINK_KEY_LENGTH: Final = 24
RESULT_ID_LENGTH: Final = 16
ERROR_TEXT_LIMIT: Final = 300

TITLES: Final[tuple[str, ...]] = (
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
