import json
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from config import settings

log = structlog.get_logger()


async def init_db() -> None:
    db_path = Path(settings.DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS media_cache (
                url TEXT PRIMARY KEY,
                file_ids_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS inline_links (
                key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.commit()
    log.info("database_initialized", path=settings.DATABASE_PATH)


async def get_cached_media(url: str) -> list[dict[str, Any]] | None:
    async with (
        aiosqlite.connect(settings.DATABASE_PATH) as db,
        db.execute("SELECT file_ids_json FROM media_cache WHERE url = ?", (url,)) as cursor,
    ):
        row = await cursor.fetchone()
        if row:
            return json.loads(row[0])  # type: ignore[no-any-return]
    return None


async def set_cached_media(url: str, file_ids: list[dict[str, Any]]) -> None:
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO media_cache (url, file_ids_json) VALUES (?, ?)",
            (url, json.dumps(file_ids)),
        )
        await db.commit()
    log.debug("media_cached", url=url)


async def save_inline_link(key: str, url: str) -> None:
    """Remember which URL a placeholder's button and result id stand for."""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO inline_links (key, url) VALUES (?, ?)",
            (key, url),
        )
        await db.commit()


async def get_inline_link(key: str) -> str | None:
    async with (
        aiosqlite.connect(settings.DATABASE_PATH) as db,
        db.execute("SELECT url FROM inline_links WHERE key = ?", (key,)) as cursor,
    ):
        row = await cursor.fetchone()
    return str(row[0]) if row else None
