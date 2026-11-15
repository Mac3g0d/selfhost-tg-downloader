"""End-to-end benchmark against a local fake Telegram Bot API.

Real downloads, the real handlers and a real (temporary, empty) SQLite cache;
only Telegram is replaced by a local HTTP server, optionally throttled to
emulate the server uplink and delayed to emulate the round trip to Telegram.
No bot token is needed and nothing is sent to Telegram. The production cache
database is never opened.

    uv run --frozen python scripts/bench_e2e.py --mode both --repeats 5 \\
        --uplink-mbit 20 --latency-ms 100 URL [URL ...]

Every repeat starts from an empty cache: each URL is requested once (miss) and
once more (hit), through the inline handler, the chat-message handler or both.
With --duplicates N the first URL is additionally requested N times
concurrently on an empty cache to show repeated work for one URL.
"""

# The benchmark genuinely needs stdlib, aiogram, aiohttp and project imports.
# flake8: noqa: WPS201
import argparse
import asyncio
import itertools
import json
import os
import secrets
import statistics
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Awaitable, Iterable, Iterator, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import structlog
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import (
    Chat,
    ChosenInlineResult,
    InlineQuery,
    Message,
    Update,
    User,
)
from aiohttp import web

os.environ["TELEGRAM_BOT_TOKEN"] = "1:benchmark-placeholder"  # noqa: S105
os.environ["BUFFER_CHAT_ID"] = "-1000000000001"
BENCH_DIR = Path(tempfile.mkdtemp(prefix="tg-e2e-"))
os.environ["DATABASE_PATH"] = str(BENCH_DIR / "cache.db")
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from bot import create_dispatcher  # noqa: E402
from config import settings  # noqa: E402
from database import init_db  # noqa: E402
from utils import clean_url  # noqa: E402

type Rows = list[dict[str, Any]]

INLINE = "inline"
CHAT = "chat"
BOTH = "both"
MISS = "miss"
HIT = "hit"
CACHE_STATES = (MISS, HIT)

SEND_VIDEO = "sendVideo"
SEND_PHOTO = "sendPhoto"
SEND_MESSAGE = "sendMessage"
ANSWER_INLINE_QUERY = "answerInlineQuery"
UPLOAD_METHODS = (SEND_VIDEO, SEND_PHOTO)

LOCALHOST = "127.0.0.1"
MAX_BODY_BYTES = 1024**3
CHUNK_BYTES = 65_536
BYTES_PER_MBIT = 125_000
MS_PER_S = 1000
BENCH_USER_ID = 42
NO_LIMIT = float(0)
TAIL_PERCENTILE = 0.95
DEFAULT_PAUSE_S = 2.0

TIMING_EVENTS = ("inline_timing", "message_timing")
IGNORED_FIELDS = ("event", "log_level", "req_id")
STAGES = ("total_ms", "download_ms", "upload_ms", "status_ms", "answer_ms", "edit_ms")

MODE_WIDTH = 7
CACHE_WIDTH = 6
URL_WIDTH = 40
COUNT_WIDTH = 3
CELL_WIDTH = 20
URL_TAIL = URL_WIDTH - 1

USER = User(id=BENCH_USER_ID, is_bot=False, first_name="bench")
PARSER = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
CLI_OPTIONS = (
    partial(PARSER.add_argument, "urls", nargs="+"),
    partial(PARSER.add_argument, "--mode", choices=[INLINE, CHAT, BOTH], default=INLINE),
    partial(PARSER.add_argument, "--repeats", type=int, default=1),
    partial(
        PARSER.add_argument, "--uplink-mbit", type=float, default=NO_LIMIT, help="0 = unthrottled"
    ),
    partial(
        PARSER.add_argument,
        "--latency-ms",
        type=float,
        default=NO_LIMIT,
        help="added to every API call",
    ),
    partial(PARSER.add_argument, "--duplicates", type=int, default=0),
    partial(PARSER.add_argument, "--pause", type=float, default=DEFAULT_PAUSE_S),
    partial(PARSER.add_argument, "--json", type=Path, help="write raw runs to this file"),
)
REGISTERED = frozenset(register() for register in CLI_OPTIONS)
HEADER_LEAD = ("mode", "cache", "url", "n")
MODE_KEY = "mode"
JOB_KEYS = (("download_ms", "job_download_ms"), ("upload_ms", "job_upload_ms"))


def _emit(text: str, *, flush: bool = False) -> None:
    print(text, flush=flush)  # noqa: T201


class FakeTelegram:
    def __init__(self, uplink_mbit: float, latency_ms: float) -> None:
        self.bytes_per_s = uplink_mbit * BYTES_PER_MBIT if uplink_mbit else NO_LIMIT
        self.latency_s = latency_ms / MS_PER_S
        self.calls: Counter[str] = Counter()
        self.upload_bytes = 0
        self.inline_results: Rows = []
        self._ids = 0

    async def respond(self, request: web.Request) -> web.Response:
        method = request.match_info["method"]
        self.calls[method] += 1
        started = time.perf_counter()
        if method == ANSWER_INLINE_QUERY:
            form = await request.post()
            self.inline_results = json.loads(str(form["results"]))
        size = await self._drain_body(request, started)
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        self._ids += 1
        return web.json_response({"ok": True, "result": self._payload(method, size)})

    async def _drain_body(self, request: web.Request, started: float) -> int:
        size = 0
        async for chunk in request.content.iter_chunked(CHUNK_BYTES):
            size += len(chunk)
            if self.bytes_per_s:
                ahead = size / self.bytes_per_s - (time.perf_counter() - started)
                if ahead > 0:
                    await asyncio.sleep(ahead)
        return size

    def _payload(self, method: str, size: int) -> Any:
        if method in UPLOAD_METHODS:
            self.upload_bytes += size
        extras = self._extras(method)
        return True if extras is None else {**self._base_message(), **extras}

    def _base_message(self) -> dict[str, Any]:
        chat = {"id": settings.BUFFER_CHAT_ID, "type": "channel", "title": "buffer"}
        return {"message_id": self._ids, "date": 0, "chat": chat}

    def _extras(self, method: str) -> dict[str, Any] | None:
        if method == SEND_VIDEO:
            video = {"file_id": f"video-{self._ids}", "file_unique_id": f"v{self._ids}"}
            return {"video": {**video, "width": 1, "height": 1, "duration": 1}}
        if method == SEND_PHOTO:
            photo = {"file_id": f"photo-{self._ids}", "file_unique_id": f"p{self._ids}"}
            return {"photo": [{**photo, "width": 1, "height": 1}]}
        if method == SEND_MESSAGE:
            return {"text": "ok"}
        return None


@dataclass(frozen=True)
class Updates:
    user: User

    def inline(self, url: str, update_id: int) -> Update:
        ident = str(update_id)
        query = InlineQuery(id=ident, from_user=self.user, query=url, offset="")
        return Update(update_id=update_id, inline_query=query)

    def chosen(self, url: str, update_id: int, result_id: str) -> Update:
        chosen = ChosenInlineResult(
            result_id=result_id,
            from_user=self.user,
            query=url,
            inline_message_id=f"bench-{update_id}-{secrets.token_hex(4)}",
        )
        return Update(update_id=update_id, chosen_inline_result=chosen)

    def chat(self, url: str, update_id: int) -> Update:
        message = Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=self.user.id, type="private"),
            from_user=self.user,
            text=url,
        )
        return Update(update_id=update_id, message=message)


@dataclass(frozen=True)
class Rig:
    dispatcher: Any
    bot: Bot
    fake: FakeTelegram
    runner: web.AppRunner
    update_ids: Iterator[int]

    @classmethod
    async def start(cls, fake: FakeTelegram) -> Rig:
        runner, port = await cls._listen(fake)
        await init_db()
        api = TelegramAPIServer.from_base(f"http://{LOCALHOST}:{port}")
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, session=AiohttpSession(api=api))
        return cls(create_dispatcher(), bot, fake, runner, itertools.count(1))

    async def request(self, mode: str, url: str) -> None:
        updates = Updates(USER)
        update_id = next(self.update_ids)
        if mode == INLINE:
            await self.dispatcher.feed_update(self.bot, updates.inline(url, update_id))
            result_id = self._placeholder_id()
            update = None if result_id is None else updates.chosen(url, update_id, result_id)
        else:
            update = updates.chat(url, update_id)
        if update is not None:
            await self.dispatcher.feed_update(self.bot, update)

    async def reset_cache(self) -> None:
        Path(settings.DATABASE_PATH).unlink(missing_ok=True)
        await init_db()

    def timings(self, logs: Iterable[Mapping[str, Any]]) -> Rows:
        events = (entry for entry in logs if entry.get("event") in TIMING_EVENTS)
        return [self._timing_row(entry) for entry in events]

    @classmethod
    async def _listen(cls, fake: FakeTelegram) -> tuple[web.AppRunner, int]:
        app = web.Application(client_max_size=MAX_BODY_BYTES)
        app.router.add_post("/bot{token}/{method}", fake.respond)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, LOCALHOST, 0)
        await site.start()
        return runner, site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    def _placeholder_id(self) -> str | None:
        # A cache miss is answered with a placeholder: "send" it, as a user would,
        # and wait until the bot has replaced it with the media.
        answers = self.fake.inline_results
        first = answers[0] if answers else {}
        return first["id"] if first.get("type") == "article" else None

    def _timing_row(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(entry)
        for name in IGNORED_FIELDS:
            row.pop(name, None)
        job_values = {stage: row[key] for stage, key in JOB_KEYS if key in row}
        return {**row, **job_values}


@dataclass(frozen=True)
class Table:
    runs: Rows
    urls: list[str]
    modes: list[str]

    def percentile(self, samples: list[float], fraction: float) -> float:
        ordered = sorted(samples)
        ordered.append(ordered[-1])
        position = (len(ordered) - 2) * fraction
        index = int(position)
        lower, upper = ordered[index : index + 2]
        return lower + (upper - lower) * (position - index)

    def print_table(self) -> None:
        _emit(self._header())
        for mode, url, cache in itertools.product(self.modes, self.urls, CACHE_STATES):
            line = self._row(mode, url, cache)
            if line is not None:
                _emit(line)

    def _leading(self, mode: str, cache: str, url: str, count: str) -> str:
        columns = ((mode, MODE_WIDTH), (cache, CACHE_WIDTH), (url, URL_WIDTH))
        cells = [text.ljust(width) for text, width in columns]
        return "".join((*cells, count.rjust(COUNT_WIDTH), "  "))

    def _header(self) -> str:
        titles = (f"{stage.removesuffix('_ms')} p50/p95" for stage in STAGES)
        cells = (title.rjust(CELL_WIDTH) for title in titles)
        lead = self._leading(*HEADER_LEAD)
        return "".join(("\n", lead, *cells))

    def _cell(self, group: Rows, stage: str) -> str:
        samples = [run[stage] / MS_PER_S for run in group if stage in run]
        if not samples:
            return "-".rjust(CELL_WIDTH)
        median = format(statistics.median(samples), "9.2f")
        tail = format(self.percentile(samples, TAIL_PERCENTILE), "<9.2f")
        return f"{median}/{tail} "

    def _row(self, mode: str, url: str, cache: str) -> str | None:
        wanted = {MODE_KEY: mode, "url": url, "cache": cache}
        group = [run for run in self.runs if wanted.items() <= run.items()]
        if not group:
            return None
        tail = url[-URL_TAIL:]
        leading = self._leading(mode, cache, tail, str(len(group)))
        return leading + "".join(self._cell(group, stage) for stage in STAGES)


type Steps = Iterable[Awaitable[list[Any]]]


@dataclass(frozen=True)
class Benchmark:
    args: argparse.Namespace
    rig: Rig

    async def duplicate_test(self) -> dict[str, Any]:
        calls = self.rig.fake.calls
        await self.rig.reset_cache()
        before = calls[SEND_VIDEO] + calls[SEND_PHOTO]
        started = time.perf_counter()
        with structlog.testing.capture_logs() as logs:
            await asyncio.gather(
                *(
                    self.rig.request(self.args.modes[0], self.args.urls[0])
                    for _ in range(self.args.duplicates)
                )
            )
            downloads = sum(1 for entry in logs if entry.get("event") == "starting_download")
        return {
            "url": self.args.urls[0],
            "concurrent_queries": self.args.duplicates,
            "downloads_started": downloads,
            "uploads": calls[SEND_VIDEO] + calls[SEND_PHOTO] - before,
            "wall_ms": round((time.perf_counter() - started) * MS_PER_S, 1),
        }

    async def run(self) -> dict[str, Any]:
        config = {
            MODE_KEY: self.args.mode,
            "repeats": self.args.repeats,
            "uplink_mbit": self.args.uplink_mbit,
            "latency_ms": self.args.latency_ms,
        }
        _emit(json.dumps({"config": config}), flush=True)
        async with AsyncExitStack() as cleanup:
            cleanup.push_async_callback(self.rig.runner.cleanup)
            cleanup.push_async_callback(self.rig.bot.session.close)
            measured = await self._measure()
        fake = self.rig.fake
        calls = dict(fake.calls)
        return {
            **measured,
            "config": config,
            "telegram_calls": calls,
            "upload_bytes": fake.upload_bytes,
        }

    async def _in_order(self, steps: Steps) -> list[Any]:
        """Await lazily created steps one after another and concatenate their results."""
        collected: list[Any] = []
        for step in steps:
            collected.extend(await step)  # noqa: WPS476 sequential by design: shared cache
        return collected

    async def _timed_request(self, mode: str, url: str, expected: str) -> Rows:
        with structlog.testing.capture_logs() as logs:
            await self.rig.request(mode, url)
            rows = [{**row, MODE_KEY: mode} for row in self.rig.timings(logs)]
        for row in rows:
            if row.get("cache") != expected:
                _emit(f"!! {mode} {url}: expected cache {expected}")
        return rows

    async def _url_pass(self, mode: str, url: str) -> Rows:
        steps = (self._timed_request(mode, url, state) for state in CACHE_STATES)
        rows = await self._in_order(steps)
        await asyncio.sleep(self.args.pause)
        return rows

    async def _mode_pass(self, mode: str) -> Rows:
        await self.rig.reset_cache()
        urls = self.args.urls
        return await self._in_order(self._url_pass(mode, url) for url in urls)

    async def _measure(self) -> dict[str, Any]:
        modes = self.args.modes
        repeats = range(self.args.repeats)
        passes = (self._mode_pass(mode) for _ in repeats for mode in modes)
        measured: dict[str, Any] = {"runs": await self._in_order(passes)}
        if self.args.duplicates:
            duplicate = await self.duplicate_test()
            _emit(json.dumps(duplicate, ensure_ascii=False))
            measured["duplicate_test"] = duplicate
        return measured


async def main() -> int:
    args = PARSER.parse_args()
    args.urls = [clean_url(url.strip()) for url in args.urls]
    args.modes = [INLINE, CHAT] if args.mode == BOTH else [args.mode]
    rig = await Rig.start(FakeTelegram(args.uplink_mbit, args.latency_ms))
    report = await Benchmark(args, rig).run()
    Table(report["runs"], args.urls, args.modes).print_table()
    calls = json.dumps({"telegram_calls": report["telegram_calls"]})
    _emit(f"\n{calls}")
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
