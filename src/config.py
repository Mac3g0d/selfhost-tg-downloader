from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from constants import TELEGRAM_FILE_LIMIT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    TELEGRAM_BOT_TOKEN: str
    BUFFER_CHAT_ID: int = 0
    DATABASE_PATH: str = "data/cache.db"
    DOWNLOAD_DIR: str = str(Path.home() / ".cache" / "tg-downloads")
    COOKIES_FILE: str = "cookies/instagram.txt"
    INSTAGRAM_USER: str = ""
    INSTAGRAM_PASS: str = ""
    max_telegram_file_size: int = Field(default=TELEGRAM_FILE_LIMIT)
    gallery_dl_bin: str = "gallery-dl"
    DOWNLOAD_TIMEOUT: int = 120
    USE_ARIA2: bool = False
    CONCURRENT_FRAGMENTS: int = 5


settings = Settings()
