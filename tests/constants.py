"""Domain facts that define the specification but are absent from the app's `constants`."""

from typing import Final

TIKTOK_HOSTS: Final[tuple[str, ...]] = (
    "www.tiktok.com",
    "tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
    "m.tiktok.com",
    "p.tiktok.com",
)
INSTAGRAM_HOSTS: Final[tuple[str, ...]] = (
    "www.instagram.com",
    "instagram.com",
    "instagr.am",
    "www.instagr.am",
)
SUPPORTED_HOSTS: Final[tuple[str, ...]] = TIKTOK_HOSTS + INSTAGRAM_HOSTS
FOREIGN_HOSTS: Final[tuple[str, ...]] = ("youtube.com", "twitter.com", "example.com")
INSTAGRAM_POST_KINDS: Final[tuple[str, ...]] = ("reel", "p")
GALLERY_DL_HOST: Final = "www.instagram.com"
GALLERY_DL_POST_KIND: Final = "p"
UNSUPPORTED_TLD: Final = "invalid"

SCHEME_HTTP: Final = "http"
SCHEME_HTTPS: Final = "https"
SCHEME_SEPARATOR: Final = "://"
TRACKING_SEPARATOR: Final = "?"
EMPTY_TEXT: Final = ""

DISTRIBUTION_NAME: Final = "selfhost-tg-downloader"
ENTRY_POINT_NAME: Final = "bot"
ENTRY_POINT_TARGET: Final = "tg_downloader:main"
PACKAGE_MODULES: Final[tuple[str, ...]] = (
    "tg_downloader",
    "bot",
    "database",
    "downloader.gallery",
    "handlers.inline",
    "handlers.media",
    "healthcheck",
)

HTML_LT: Final = "<"
HTML_GT: Final = ">"
HTML_AMP: Final = "&"
HTML_LT_ESCAPED: Final = "&lt;"
HTML_GT_ESCAPED: Final = "&gt;"
HTML_AMP_ESCAPED: Final = "&amp;"
FAILURE_MARK: Final = "❌"
FAILURE_MARKUP_ALLOWANCE: Final = 100

PREVIOUS_LABEL: Final = "◀️"
NEXT_LABEL: Final = "▶️"
PAGE_COUNTER_TEMPLATE: Final = "{page} / {total}"
PAGE_SEPARATOR: Final = ":"
UNCACHED_SECONDS: Final = 0

UNSUPPORTED_URL_MESSAGE: Final = "Unsupported URL"
CANCELLED_MESSAGE: Final = "Download cancelled"
TIMED_OUT_MESSAGE: Final = "timed out"
UNBOUND_MESSAGE_PATTERN: Final = "Message is not bound to a bot"

COOKIES_KEY: Final = "cookies"
USERNAME_KEY: Final = "username"
PASSWORD_KEY: Final = "password"
MTIME_KEY: Final = "mtime"
BASE_DIRECTORY_KEY: Final = "base-directory"
OUTPUT_PATH: Final[tuple[str, ...]] = ("output",)
OUTPUT_MODE_KEY: Final = "mode"
OUTPUT_MODE_NULL: Final = "null"

FOREIGN_EXTENSIONS: Final[tuple[str, ...]] = (".pdf", ".docx", ".html", ".txt")
PEER_TIMEOUT_SECONDS: Final = 1
COLLECT_NAME_MIN_CHARS: Final = 8
COLLECT_NAME_MAX_CHARS: Final = 16
COLLECT_CONTENT_LENGTH: Final = 16

GALLERY_DOWNLOAD_TIMING_KEY: Final = "download_ms"
GALLERY_JOB_TIMEOUT_SECONDS: Final = 0.01
GALLERY_JOB_WAIT_SECONDS: Final = 5
GALLERY_CLEANUP_WAIT_SECONDS: Final = 1
GALLERY_POLL_SECONDS: Final = 0.001
GALLERY_RUN_JOB_TARGET: Final = "downloader.gdl_job.run_job"
GALLERY_RMTREE_TARGET: Final = "downloader.gallery.shutil.rmtree"
GALLERY_FAILURE_STATUS_MAX: Final = 255
