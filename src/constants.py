"""Constants shared by the bot modules."""

import re

from aiogram import F as EVENT_FILTER
from aiogram import types

MS_PER_SECOND = 1000
BYTES_PER_MB = 1024 * 1024

TELEGRAM_LIMIT_MB = 50
TELEGRAM_FILE_LIMIT = TELEGRAM_LIMIT_MB * 1024 * 1024

WORKER_PREFIX = "gallery-dl"
UNSUPPORTED_URL_STATUS = 64
CANCELLED_STATUS = 1
INSTAGRAM_PATH = ("extractor", "instagram")

VIDEO_EXTENSIONS: frozenset[str] = frozenset((".mp4", ".mov", ".mkv", ".webm", ".avi"))
IMAGE_EXTENSIONS: frozenset[str] = frozenset((".jpg", ".jpeg", ".png", ".webp"))
MAX_PARALLEL_DOWNLOADS = 8
WORK_DIR_PREFIX = "dl-"

URL_PATTERN: re.Pattern[str] = re.compile(
    r"https?://(?:"
    r"(?:www\.|vm\.|vt\.|p\.|m\.)?tiktok\.com"
    r"|(?:www\.)?instagram\.com"
    r"|(?:www\.)?instagr\.am"
    r")/[\w\-./?%&=+@]*",
    re.IGNORECASE,
)

KEY_TYPE = "type"
KEY_FILE_ID = "file_id"
TYPE_VIDEO = "video"
TYPE_PHOTO = "photo"

UPLOAD_ACTION = "upload_video"
SEND_FAILED_TEXT = "❌ Ошибка при отправке файла в Telegram."

WELCOME_TEXT = (
    "👋 <b>Привет!</b>\n\n"
    "Я скачиваю видео из <b>TikTok</b> и <b>Instagram</b>.\n\n"
    "Просто отправь мне ссылку — я скачаю и пришлю видео прямо сюда.\n\n"
    "🔗 <b>Поддерживаемые ссылки:</b>\n"
    "• <code>tiktok.com</code> / <code>vm.tiktok.com</code>\n"
    "• <code>instagram.com/reel/...</code>\n"
    "• <code>instagram.com/p/...</code>"
)

SHORT_CACHE_SECONDS = 5
HIT_CACHE_SECONDS = 300
MAX_ACTIVE_JOBS = 16
TEXT_BUSY = "слишком много загрузок, попробуй чуть позже"

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
