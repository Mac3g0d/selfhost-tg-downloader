"""End-to-end inline benchmark against a local fake Telegram Bot API.

Real downloads, the real inline handler and a real (temporary, empty) SQLite
cache; only Telegram is replaced by a local HTTP server, optionally throttled
to emulate the server uplink. No bot token is needed and nothing is sent to
Telegram. The production cache database is never opened.

    uv run --frozen python scripts/bench_e2e.py --uplink-mbit 20 URL [URL ...]

Modes: each URL is requested once on an empty cache (miss), then once more
(hit). With --duplicates N the first URL is additionally requested N times
concurrently on an empty cache to show repeated work for one URL.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

os.environ["TELEGRAM_BOT_TOKEN"] = "1:benchmark-placeholder"  # noqa: S105
os.environ["BUFFER_CHAT_ID"] = "-1000000000001"
_TMP = Path(tempfile.mkdtemp(prefix="tg-e2e-"))
os.environ["DATABASE_PATH"] = str(_TMP / "cache.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import structlog  # noqa: E402
from aiogram import Bot  # noqa: E402
from aiogram.client.session.aiohttp import AiohttpSession  # noqa: E402
from aiogram.client.telegram import TelegramAPIServer  # noqa: E402
from aiogram.types import InlineQuery, Update, User  # noqa: E402
from aiohttp import web  # noqa: E402

from bot import create_dispatcher  # noqa: E402
from config import settings  # noqa: E402
from database import init_db  # noqa: E402
from utils import clean_url  # noqa: E402


class FakeTelegram:
    def __init__(self, uplink_mbit: float) -> None:
        self.bytes_per_s = uplink_mbit * 1_000_000 / 8 if uplink_mbit else 0.0
        self.calls: Counter[str] = Counter()
        self.upload_bytes = 0
        self._ids = 0

    async def handle(self, request: web.Request) -> web.Response:
        method = request.match_info["method"]
        self.calls[method] += 1
        size = 0
        started = time.perf_counter()
        async for chunk in request.content.iter_chunked(64 * 1024):
            size += len(chunk)
            if self.bytes_per_s:
                ahead = size / self.bytes_per_s - (time.perf_counter() - started)
                if ahead > 0:
                    await asyncio.sleep(ahead)
        self._ids += 1
        chat = {"id": settings.BUFFER_CHAT_ID, "type": "channel", "title": "buffer"}
        message: dict[str, Any] = {"message_id": self._ids, "date": 0, "chat": chat}
        result: Any = True
        if method == "sendVideo":
            self.upload_bytes += size
            message["video"] = {
                "file_id": f"video-{self._ids}",
                "file_unique_id": f"v{self._ids}",
                "width": 1,
                "height": 1,
                "duration": 1,
            }
            result = message
        elif method == "sendPhoto":
            self.upload_bytes += size
            message["photo"] = [
                {
                    "file_id": f"photo-{self._ids}",
                    "file_unique_id": f"p{self._ids}",
                    "width": 1,
                    "height": 1,
                }
            ]
            result = message
        elif method == "sendMessage":
            message["text"] = "ok"
            result = message
        return web.json_response({"ok": True, "result": result})


async def _inline(dp: Any, bot: Bot, url: str, update_id: int) -> None:
    user = User(id=42, is_bot=False, first_name="bench")
    query = InlineQuery(id=str(update_id), from_user=user, query=url, offset="")
    await dp.feed_update(bot, Update(update_id=update_id, inline_query=query))


def _timings(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keep = []
    for entry in logs:
        if entry.get("event") == "inline_timing":
            keep.append({k: v for k, v in entry.items() if k not in {"event", "log_level"}})
    return keep


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--uplink-mbit", type=float, default=0.0, help="0 = unthrottled")
    parser.add_argument("--duplicates", type=int, default=0)
    parser.add_argument("--pause", type=float, default=2.0)
    args = parser.parse_args()
    urls = [clean_url(u.strip()) for u in args.urls]

    fake = FakeTelegram(args.uplink_mbit)
    app = web.Application(client_max_size=1024**3)
    app.router.add_post("/bot{token}/{method}", fake.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    await init_db()
    session = AiohttpSession(api=TelegramAPIServer.from_base(f"http://127.0.0.1:{port}"))
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, session=session)
    dp = create_dispatcher()

    report: dict[str, Any] = {"uplink_mbit": args.uplink_mbit, "runs": []}
    update_id = 0
    try:
        for url in urls:
            for expected in ("miss", "hit"):
                update_id += 1
                with structlog.testing.capture_logs() as logs:
                    await _inline(dp, bot, url, update_id)
                for row in _timings(logs):
                    row.pop("req_id", None)
                    report["runs"].append(row)
                    print(json.dumps(row, ensure_ascii=False), flush=True)  # noqa: T201
                    if row.get("cache") != expected:
                        print(f"!! expected cache {expected}", flush=True)  # noqa: T201
            await asyncio.sleep(args.pause)

        if args.duplicates:
            Path(settings.DATABASE_PATH).unlink()
            await init_db()
            before = fake.calls.copy()
            started = time.perf_counter()
            with structlog.testing.capture_logs() as logs:
                await asyncio.gather(
                    *(_inline(dp, bot, urls[0], update_id + i + 1) for i in range(args.duplicates))
                )
            downloads = sum(1 for e in logs if e.get("event") == "starting_download")
            duplicate = {
                "url": urls[0],
                "concurrent_queries": args.duplicates,
                "downloads_started": downloads,
                "uploads": (fake.calls["sendVideo"] + fake.calls["sendPhoto"])
                - (before["sendVideo"] + before["sendPhoto"]),
                "wall_ms": round((time.perf_counter() - started) * 1000, 1),
            }
            report["duplicate_test"] = duplicate
            print(json.dumps(duplicate, ensure_ascii=False))  # noqa: T201
    finally:
        await bot.session.close()
        await runner.cleanup()

    report["telegram_calls"] = dict(fake.calls)
    report["upload_bytes"] = fake.upload_bytes
    print(json.dumps({"telegram_calls": report["telegram_calls"]}))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
