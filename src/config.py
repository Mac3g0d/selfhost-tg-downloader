from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    TELEGRAM_BOT_TOKEN: str
    BUFFER_CHAT_ID: int = 0
    DOWNLOAD_DIR: str = "/tmp/tg-downloads"
    COOKIES_FILE: str = "cookies/instagram.txt"
    INSTAGRAM_USER: str = ""
    INSTAGRAM_PASS: str = ""
    max_telegram_file_size: int = Field(default=50 * 1024 * 1024)
    gallery_dl_bin: str = "gallery-dl"
    DOWNLOAD_TIMEOUT: int = 120


settings = Settings()
