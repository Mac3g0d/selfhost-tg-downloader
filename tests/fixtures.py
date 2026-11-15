"""All test fixtures and the helper types they need.

Sections: shared core, builders, link detection, in-flight locks, inline mode, gallery-dl,
chat delivery and media collection. Everything random comes from the `faker` fixture.
"""

import asyncio
import itertools
import threading
import types
import typing
from collections import abc
from importlib import import_module, metadata
from pathlib import Path
from shutil import copyfile, rmtree
from unittest import mock

import pytest
from aiogram import exceptions, methods
from aiogram import types as tg
from faker import Faker
from gallery_dl import config as gdl_config
from pytest_mock import MockerFixture

import constants as app
import database
import inflight
from config import Settings, settings
from downloader import gallery, gdl_job
from handlers import delivery, inline
from handlers import inline_ui as ui
from tests import constants as spec
from tests import factories
from timing import StageTimer


def _tiktok_link(faker: Faker) -> str:
    host = faker.random_element(spec.TIKTOK_HOSTS)
    path = f"@{faker.pystr(min_chars=5, max_chars=12)}/video/{faker.pyint()}"
    return f"{spec.SCHEME_HTTPS}{spec.SCHEME_SEPARATOR}{host}/{path}"


def _instagram_link(faker: Faker) -> str:
    host = faker.random_element(spec.INSTAGRAM_HOSTS)
    kind = faker.random_element(spec.INSTAGRAM_POST_KINDS)
    token = faker.pystr(min_chars=8, max_chars=12)
    return f"{spec.SCHEME_HTTPS}{spec.SCHEME_SEPARATOR}{host}/{kind}/{token}"


@pytest.fixture(scope="session")
def faker() -> Faker:
    """One shared, unseeded Faker (English and Russian locales) for all generated scalars."""
    return Faker(["en_US", "ru_RU"])


@pytest.fixture(scope="session")
def settings_defaults() -> dict[str, typing.Any]:
    """The default values of every setting, computed once per session from the isolated env."""
    return Settings().model_dump()


@pytest.fixture(autouse=True)
def _test_settings(
    settings_defaults: dict[str, typing.Any], tmp_path: Path
) -> abc.Generator[None]:
    """Reset the shared `config.settings` to its defaults for the test and again afterwards.

    DATABASE_PATH and DOWNLOAD_DIR point at not yet created names inside `tmp_path`, so no
    test can touch the real cache database or download directory.
    """
    settings.__dict__.update(settings_defaults)
    settings.DATABASE_PATH = str(tmp_path / "cache.db")
    settings.DOWNLOAD_DIR = str(tmp_path / "downloads")
    yield
    settings.__dict__.update(settings_defaults)


@pytest.fixture(autouse=True)
def _clean_gallery_dl_config() -> abc.Generator[None]:
    """Clear gallery-dl's process-wide configuration after every test."""
    yield
    gdl_config.clear()


@pytest.fixture(scope="session")
def database_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A database file initialised by `init_db()` once per session; tests only copy it."""
    template = tmp_path_factory.mktemp("template") / "cache.db"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "DATABASE_PATH", str(template))
        asyncio.run(database.init_db())
    return template


@pytest.fixture
def database_ready(database_template: Path) -> Path:
    """An initialised, isolated copy of the cache database at DATABASE_PATH; return the path."""
    copy = Path(settings.DATABASE_PATH)
    copyfile(database_template, copy)
    return copy


@pytest.fixture
def download_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, faker: Faker) -> Path:
    """An empty directory inside `tmp_path`, already set as DOWNLOAD_DIR; return it."""
    directory = tmp_path / faker.pystr()
    directory.mkdir()
    monkeypatch.setattr(settings, "DOWNLOAD_DIR", str(directory))
    return directory


@pytest.fixture
def tiktok_url(faker: Faker) -> str:
    """A clean (no query, no trailing slash) supported TikTok link on a random supported host."""
    return _tiktok_link(faker)


@pytest.fixture
def instagram_url(faker: Faker) -> str:
    """A clean supported Instagram reel or post link on a random supported host."""
    return _instagram_link(faker)


@pytest.fixture(params=["tiktok_url", "instagram_url"])
def supported_url(request: pytest.FixtureRequest) -> str:
    """A clean supported link; the test runs once with a TikTok and once with an Instagram one."""
    return str(request.getfixturevalue(request.param))


@pytest.fixture
def make_url(faker: Faker) -> abc.Callable[[], str]:
    """Factory: every call returns a new clean supported link (TikTok or Instagram)."""

    def make() -> str:
        build = faker.random_element((_tiktok_link, _instagram_link))
        return str(build(faker))

    return make


@pytest.fixture
def gallery_dl_url(faker: Faker) -> str:
    """An Instagram post link that a real gallery-dl extractor accepts (for `Job(...)`)."""
    token = faker.pystr(min_chars=8, max_chars=12)
    root = f"{spec.SCHEME_HTTPS}{spec.SCHEME_SEPARATOR}{spec.GALLERY_DL_HOST}"
    return f"{root}/{spec.GALLERY_DL_POST_KIND}/{token}"


@pytest.fixture
def unsupported_url(faker: Faker) -> str:
    """A link no gallery-dl extractor and not the bot supports (reserved `.invalid` TLD)."""
    name = faker.pystr(min_chars=5, max_chars=12).lower()
    return (
        f"{spec.SCHEME_HTTPS}{spec.SCHEME_SEPARATOR}{name}.{spec.UNSUPPORTED_TLD}/{faker.pystr()}"
    )


@pytest.fixture
def video_file_id(faker: Faker) -> str:
    """The Telegram file id that `bot.send_video` reports back."""
    return str(faker.pystr(min_chars=10, max_chars=30))


@pytest.fixture
def photo_file_id(faker: Faker) -> str:
    """The Telegram file id that `bot.send_photo` reports back (as the last photo size)."""
    return str(faker.pystr(min_chars=10, max_chars=30))


@pytest.fixture
def bot(
    mocker: MockerFixture, faker: Faker, video_file_id: str, photo_file_id: str
) -> mock.AsyncMock:
    """An AsyncMock bot with a random `id`.

    `send_video` returns an object whose `.video.file_id` is `video_file_id`; `send_photo`
    one whose `.photo[-1].file_id` is `photo_file_id`. Every other method is a plain AsyncMock.
    """
    stub: mock.AsyncMock = mocker.AsyncMock(id=faker.pyint(min_value=1))
    stub.send_video.return_value = types.SimpleNamespace(
        video=types.SimpleNamespace(file_id=video_file_id)
    )
    stub.send_photo.return_value = types.SimpleNamespace(
        photo=[types.SimpleNamespace(file_id=photo_file_id)]
    )
    return stub


@pytest.fixture
def user() -> tg.User:
    """A random human user."""
    return factories.UserFactory.build()


@pytest.fixture
def chat() -> tg.Chat:
    """A random private chat."""
    return factories.ChatFactory.build()


@pytest.fixture
def inline_message_id(faker: Faker) -> str:
    """A random inline message id; the default for `make_chosen_result` and `make_callback`."""
    return str(faker.pystr())


@pytest.fixture
def make_message(bot: mock.AsyncMock) -> abc.Callable[..., tg.Message]:
    """Factory `make(text=None, *, bound=True, **fields)` -> Message in a random private chat.

    Bound to the `bot` fixture unless `bound=False`; extra keyword fields override the factory.
    """

    def make(text: str | None = None, *, bound: bool = True, **fields: typing.Any) -> tg.Message:
        message = factories.MessageFactory.build(text=text, **fields)
        return message.as_(bot) if bound else message

    return make


@pytest.fixture
def make_inline_query(bot: mock.AsyncMock) -> abc.Callable[..., tg.InlineQuery]:
    """Factory `make(query=None, **fields)` -> InlineQuery bound to `bot`.

    Without `query` the text is random; `from_user` is a random user unless overridden.
    """

    def make(query: str | None = None, **fields: typing.Any) -> tg.InlineQuery:
        if query is not None:
            fields["query"] = query
        return factories.InlineQueryFactory.build(**fields).as_(bot)

    return make


@pytest.fixture
def make_chosen_result(
    bot: mock.AsyncMock, faker: Faker, inline_message_id: str
) -> abc.Callable[..., tg.ChosenInlineResult]:
    """Factory `make(result_id=None, **fields)` -> ChosenInlineResult bound to `bot`.

    `inline_message_id` defaults to the fixture of that name; `result_id` defaults to
    `PLACEHOLDER_PREFIX` plus a random key.
    """

    def make(result_id: str | None = None, **fields: typing.Any) -> tg.ChosenInlineResult:
        defaults: dict[str, typing.Any] = {
            "result_id": result_id or app.PLACEHOLDER_PREFIX + faker.pystr(),
            "inline_message_id": inline_message_id,
        }
        return factories.ChosenInlineResultFactory.build(**{**defaults, **fields}).as_(bot)

    return make


@pytest.fixture
def make_callback(
    bot: mock.AsyncMock, inline_message_id: str
) -> abc.Callable[..., tg.CallbackQuery]:
    """Factory `make(payload=None, **fields)` -> CallbackQuery bound to `bot`.

    `inline_message_id` defaults to the fixture of that name; `payload` becomes the button data.
    """

    def make(payload: str | None = None, **fields: typing.Any) -> tg.CallbackQuery:
        defaults: dict[str, typing.Any] = {"data": payload, "inline_message_id": inline_message_id}
        return factories.CallbackQueryFactory.build(**{**defaults, **fields}).as_(bot)

    return make


class LinkText(typing.NamedTuple):
    """A message text and the cleaned links the bot has to find in it."""

    text: str
    expected: list[str]


@pytest.fixture(params=spec.SUPPORTED_HOSTS)
def supported_host(request: pytest.FixtureRequest) -> str:
    """Every host the bot supports, one test run per host."""
    return str(request.param)


@pytest.fixture
def host_link(supported_host: str, faker: Faker) -> LinkText:
    """A link on `supported_host` with a trailing slash; the slash is not expected back."""
    path = f"{faker.pystr()}/{faker.pystr()}"
    link = f"{spec.SCHEME_HTTPS}{spec.SCHEME_SEPARATOR}{supported_host}/{path}"
    return LinkText(text=f"{link}/", expected=[link])


@pytest.fixture
def surrounded_link(supported_url: str, faker: Faker) -> LinkText:
    """A link with a trailing slash between two sentences."""
    return LinkText(
        text=f"{faker.sentence()} {supported_url}/ {faker.sentence()}", expected=[supported_url]
    )


@pytest.fixture
def padded_link(supported_url: str, faker: Faker) -> LinkText:
    """A link with random runs of spaces around it."""
    padding = " " * faker.pyint(min_value=1, max_value=5)
    return LinkText(text=f"{padding}{supported_url}{padding}", expected=[supported_url])


@pytest.fixture
def two_links(tiktok_url: str, instagram_url: str, faker: Faker) -> LinkText:
    """Two links with trailing slashes in one sentence, in this order."""
    first = f"{faker.word()} {instagram_url}/"
    second = f"{faker.word()} {tiktok_url}/ {faker.word()}"
    return LinkText(text=f"{first} {second}", expected=[instagram_url, tiktok_url])


@pytest.fixture
def spaced_links(tiktok_url: str, instagram_url: str, faker: Faker) -> LinkText:
    """Two links separated by a run of two or more spaces and nothing else."""
    gap = " " * faker.pyint(min_value=2, max_value=6)
    return LinkText(
        text=f"{instagram_url}{gap}{tiktok_url}/", expected=[instagram_url, tiktok_url]
    )


@pytest.fixture
def tracked_link(supported_url: str, faker: Faker) -> LinkText:
    """A link carrying a query string that must be stripped."""
    query = f"{faker.pystr()}={faker.pystr()}"
    return LinkText(
        text=f"{supported_url}{spec.TRACKING_SEPARATOR}{query}", expected=[supported_url]
    )


@pytest.fixture
def insecure_link(supported_url: str) -> LinkText:
    """The same link over plain http; the scheme is kept."""
    insecure = supported_url.replace(spec.SCHEME_HTTPS, spec.SCHEME_HTTP, 1)
    return LinkText(text=insecure, expected=[insecure])


@pytest.fixture
def shouting_link(supported_url: str) -> LinkText:
    """The whole link in upper case: the scheme is lowered, host and path keep their case."""
    shouted = supported_url.upper()
    expected = shouted.replace(spec.SCHEME_HTTPS.upper(), spec.SCHEME_HTTPS, 1)
    return LinkText(text=shouted, expected=[expected])


@pytest.fixture
def plain_text(faker: Faker) -> str:
    """A sentence without any link."""
    return str(faker.sentence())


@pytest.fixture
def empty_text() -> str:
    """The empty message text."""
    return spec.EMPTY_TEXT


@pytest.fixture(params=spec.FOREIGN_HOSTS)
def foreign_link(request: pytest.FixtureRequest, faker: Faker) -> str:
    """A link on a host the bot does not support, one test run per host."""
    return f"{spec.SCHEME_HTTPS}{spec.SCHEME_SEPARATOR}{request.param}/{faker.pystr()}"


@pytest.fixture
def bare_host_link(supported_host: str) -> str:
    """A supported host without any path."""
    return f"{spec.SCHEME_HTTPS}{spec.SCHEME_SEPARATOR}{supported_host}"


class CriticalSection:
    """Counts how many workers are inside a critical section at once."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    def enter(self) -> None:
        self.active += 1
        self.peak = max(self.peak, self.active)

    def leave(self) -> None:
        self.active -= 1


class TimedStages(typing.NamedTuple):
    """A timer that ran one stage twice on a fake clock, with the durations it must report."""

    timer: StageTimer
    stage_name: str
    stage_ms: float
    total_ms: float


@pytest.fixture
def critical_section() -> CriticalSection:
    """A fresh counter of workers inside the guarded section."""
    return CriticalSection()


@pytest.fixture
def serialized_run(
    supported_url: str, critical_section: CriticalSection, faker: Faker
) -> abc.Callable[[], abc.Awaitable[None]]:
    """Awaiting the result runs 2-5 workers on one URL; each yields once inside the lock."""
    workers = faker.pyint(min_value=2, max_value=5)

    async def worker() -> None:
        async with inflight.url_lock(supported_url):
            critical_section.enter()
            await asyncio.sleep(0)
            critical_section.leave()

    async def run() -> None:
        await asyncio.gather(*(worker() for _ in range(workers)))

    return run


@pytest.fixture
def parallel_run(
    tiktok_url: str, instagram_url: str, critical_section: CriticalSection
) -> abc.Callable[[], abc.Awaitable[None]]:
    """Awaiting the result runs two workers on different URLs; each waits for its peer."""
    both_inside = asyncio.Event()

    async def worker(url: str) -> None:
        async with inflight.url_lock(url):
            critical_section.enter()
            if critical_section.active == 2:
                both_inside.set()
            await asyncio.wait_for(both_inside.wait(), timeout=spec.PEER_TIMEOUT_SECONDS)

    async def run() -> None:
        await asyncio.gather(worker(tiktok_url), worker(instagram_url))

    return run


@pytest.fixture
def clock_ticks(faker: Faker) -> list[float]:
    """Six increasing readings of a fake clock, in whole seconds."""
    gaps = [faker.pyint(min_value=1, max_value=100) for _ in range(5)]
    return [float(tick) for tick in itertools.accumulate(gaps, initial=faker.pyint())]


@pytest.fixture
def timed_stages(mocker: MockerFixture, faker: Faker, clock_ticks: list[float]) -> TimedStages:
    """A timer whose clock is `clock_ticks`; the last tick is left for `summary()`.

    Clock reads: timer start, then start and end of two runs of one stage, then the summary.
    """
    mocker.patch("timing.time", types.SimpleNamespace(perf_counter=iter(clock_ticks).__next__))
    name = faker.pystr()
    timer = StageTimer()
    for _ in range(2):
        with timer.stage(name):
            faker.pyint()
    elapsed = [after - before for before, after in itertools.pairwise(clock_ticks)]
    return TimedStages(
        timer=timer,
        stage_name=name,
        stage_ms=(elapsed[1] + elapsed[3]) * 1000,
        total_ms=sum(elapsed) * 1000,
    )


def _first_row(markup: typing.Any) -> list[tg.InlineKeyboardButton]:
    row: list[tg.InlineKeyboardButton] = markup.inline_keyboard[0]
    return row


type CacheEntries = list[dict[str, str]]


class DownloadGate:
    """A download that starts, then blocks until `release` is set; it ends as a failure."""

    def __init__(self, download: mock.AsyncMock) -> None:
        self.download = download
        self.started = asyncio.Event()
        self.release = asyncio.Event()


class FailingDownload:
    """A failing download with a reason that needs HTML escaping, and its escaped form."""

    def __init__(self, download: mock.AsyncMock, reason: str, escaped: str) -> None:
        self.download = download
        self.reason = reason
        self.escaped = escaped


class Requests:
    """The API requests the bot double received, as method objects."""

    def __init__(self, bot: mock.AsyncMock) -> None:
        self.bot = bot

    @property
    def sent(self) -> list[typing.Any]:
        """Every request passed to the bot, in order."""
        return [call.args[0] for call in self.bot.call_args_list]

    @property
    def answer(self) -> methods.AnswerInlineQuery:
        """The only inline query answer sent."""
        answers = [req for req in self.sent if isinstance(req, methods.AnswerInlineQuery)]
        assert len(answers) == 1
        return answers[0]

    @property
    def callback_answer(self) -> methods.AnswerCallbackQuery:
        """The only request sent, which must be a callback answer."""
        assert len(self.sent) == 1
        answer = self.sent[0]
        assert isinstance(answer, methods.AnswerCallbackQuery)
        return answer

    def first_row(self, markup: typing.Any) -> list[tg.InlineKeyboardButton]:
        """The first row of buttons of a keyboard."""
        return _first_row(markup)


class Edits:
    """The message edits the bot double received."""

    def __init__(self, bot: mock.AsyncMock) -> None:
        self.bot = bot

    @property
    def edited_media(self) -> typing.Any:
        """The media object of the last media edit."""
        call = self.bot.edit_message_media.call_args
        return call.args[0]

    @property
    def edited_kwargs(self) -> dict[str, typing.Any]:
        """The keyword arguments of the last media edit."""
        call = self.bot.edit_message_media.call_args
        kwargs: dict[str, typing.Any] = call.kwargs
        return kwargs

    @property
    def edited_row(self) -> list[tg.InlineKeyboardButton]:
        """The first keyboard row of the last media edit."""
        return _first_row(self.edited_kwargs["reply_markup"])

    @property
    def status_text(self) -> str:
        """The text of the last status edit."""
        call = self.bot.edit_message_text.call_args
        text: str = call.args[0]
        return text

    @property
    def status_button(self) -> tg.InlineKeyboardButton:
        """The first button of the last status edit."""
        call = self.bot.edit_message_text.call_args
        return _first_row(call.kwargs["reply_markup"])[0]

    @property
    def status_texts(self) -> list[str]:
        """The texts of all status edits."""
        return [call.args[0] for call in self.bot.edit_message_text.call_args_list]


class Delivery(typing.NamedTuple):
    """A sent placeholder of the generated link, ready to be replaced with the media."""

    chosen: tg.ChosenInlineResult
    url: str
    key: str
    inline_message_id: str
    work_dir: Path


@pytest.fixture(autouse=True)
async def _inline_env(
    _test_settings: None, database_ready: Path, faker: Faker
) -> abc.AsyncGenerator[None]:
    """Configure the buffer chat and an initialised DB; drop leftover jobs afterwards."""
    settings.BUFFER_CHAT_ID = -faker.pyint(min_value=1)
    yield
    tasks = [job.task for job in inline._jobs.values() if job.task]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    inline._jobs.clear()
    inline._delivering.clear()


@pytest.fixture
def requests(bot: mock.AsyncMock) -> Requests:
    """The requests received by the bot double."""
    return Requests(bot)


@pytest.fixture
def edits(bot: mock.AsyncMock) -> Edits:
    """The message edits received by the bot double."""
    return Edits(bot)


@pytest.fixture
def key(supported_url: str) -> str:
    """The callback key of the generated link."""
    return ui.link_key(supported_url)


@pytest.fixture
def work_dir(tmp_path: Path, faker: Faker) -> Path:
    """A not yet created work directory of a download."""
    return tmp_path / faker.pystr()


@pytest.fixture
def stage_download(
    mocker: MockerFixture, work_dir: Path, faker: Faker
) -> abc.Callable[..., mock.AsyncMock]:
    """Factory `stage(*is_video)`: patches `download_media` to produce those files on disk."""

    def stage(*kinds: bool) -> mock.AsyncMock:
        def make(url: str) -> typing.Any:
            work_dir.mkdir(exist_ok=True)
            files = []
            for is_video in kinds:
                path = work_dir / faker.pystr()
                path.write_bytes(faker.binary(length=8))
                files.append(gallery.MediaFile(path=path, is_video=is_video))
            return factories.DownloadResultFactory.build(media_files=files, work_dir=work_dir)

        return mocker.patch.object(inline, "download_media", side_effect=make)

    return stage


@pytest.fixture
def video_download(stage_download: abc.Callable[..., mock.AsyncMock]) -> mock.AsyncMock:
    """A download that yields one video file."""
    return stage_download(True)


@pytest.fixture
def carousel_download(stage_download: abc.Callable[..., mock.AsyncMock]) -> mock.AsyncMock:
    """A download that yields two photos."""
    return stage_download(False, False)


@pytest.fixture
def slow_download(mocker: MockerFixture, faker: Faker) -> DownloadGate:
    """A download that blocks on `release` and then fails."""
    gate = DownloadGate(mocker.AsyncMock())

    async def block(url: str) -> typing.Any:
        gate.started.set()
        await gate.release.wait()
        return factories.DownloadResultFactory.build(success=False, error=faker.sentence())

    gate.download = mocker.patch.object(inline, "download_media", side_effect=block)
    return gate


@pytest.fixture
def failing_download(mocker: MockerFixture, faker: Faker) -> FailingDownload:
    """A download failing with a reason that contains angle brackets."""
    word = faker.pystr()
    reason = f"{spec.HTML_LT}{word}{spec.HTML_GT}"
    escaped = f"{spec.HTML_LT_ESCAPED}{word}{spec.HTML_GT_ESCAPED}"
    download = mocker.patch.object(
        inline,
        "download_media",
        return_value=factories.DownloadResultFactory.build(success=False, error=reason),
    )
    return FailingDownload(download, reason, escaped)


@pytest.fixture
def make_cached(faker: Faker, supported_url: str) -> abc.Callable[..., typing.Any]:
    """Async factory `cache(*kinds)`: stores entries of those types and returns them."""

    async def cache(*kinds: str) -> CacheEntries:
        entries = [{app.KEY_TYPE: kind, app.KEY_FILE_ID: faker.pystr()} for kind in kinds]
        await database.set_cached_media(supported_url, entries)
        return entries

    return cache


@pytest.fixture
async def saved_link(supported_url: str, key: str) -> None:
    """The link stored under its key, as after an inline query."""
    await database.save_inline_link(key, supported_url)


@pytest.fixture
async def cached_video(make_cached: abc.Callable[..., typing.Any]) -> CacheEntries:
    """One cached video."""
    entries: CacheEntries = await make_cached(app.TYPE_VIDEO)
    return entries


@pytest.fixture
async def cached_photo(make_cached: abc.Callable[..., typing.Any]) -> CacheEntries:
    """One cached photo."""
    entries: CacheEntries = await make_cached(app.TYPE_PHOTO)
    return entries


@pytest.fixture
async def cached_mixed_carousel(
    make_cached: abc.Callable[..., typing.Any],
) -> CacheEntries:
    """A cached photo followed by a cached video."""
    entries: CacheEntries = await make_cached(app.TYPE_PHOTO, app.TYPE_VIDEO)
    return entries


@pytest.fixture
async def cached_photo_carousel(
    make_cached: abc.Callable[..., typing.Any],
) -> CacheEntries:
    """Two cached photos."""
    entries: CacheEntries = await make_cached(app.TYPE_PHOTO, app.TYPE_PHOTO)
    return entries


@pytest.fixture
def query(
    make_inline_query: abc.Callable[..., tg.InlineQuery], supported_url: str
) -> tg.InlineQuery:
    """An inline query with the generated link."""
    return make_inline_query(supported_url)


@pytest.fixture
async def placeholder_shown(query: tg.InlineQuery, bot: mock.AsyncMock) -> None:
    """One inline query was answered with the placeholder."""
    await inline.on_inline_query(query, bot)


@pytest.fixture
async def placeholder_shown_twice(
    placeholder_shown: None,
    make_inline_query: abc.Callable[..., tg.InlineQuery],
    supported_url: str,
    bot: mock.AsyncMock,
) -> None:
    """A second inline query for the same link was answered too."""
    await inline.on_inline_query(make_inline_query(supported_url), bot)


@pytest.fixture
def chosen_delivery(
    make_chosen_result: abc.Callable[..., tg.ChosenInlineResult],
    saved_link: None,
    key: str,
    supported_url: str,
    work_dir: Path,
) -> Delivery:
    """The user sent the placeholder of the generated link; no preparation has started."""
    chosen = make_chosen_result(app.PLACEHOLDER_PREFIX + key, query=supported_url)
    assert chosen.inline_message_id is not None
    return Delivery(chosen, supported_url, key, chosen.inline_message_id, work_dir)


@pytest.fixture
def video_delivery(
    chosen_delivery: Delivery, video_download: mock.AsyncMock, placeholder_shown: None
) -> Delivery:
    """A sent placeholder whose preparation (one video) was started by an inline query."""
    return chosen_delivery


@pytest.fixture
def carousel_delivery(
    chosen_delivery: Delivery, carousel_download: mock.AsyncMock, placeholder_shown: None
) -> Delivery:
    """A sent placeholder whose preparation (two photos) was started by an inline query."""
    return chosen_delivery


@pytest.fixture
def shared_delivery(
    chosen_delivery: Delivery, video_download: mock.AsyncMock, placeholder_shown_twice: None
) -> Delivery:
    """A sent placeholder whose single preparation was requested by two inline queries."""
    return chosen_delivery


@pytest.fixture
def failing_delivery(
    chosen_delivery: Delivery, failing_download: FailingDownload, placeholder_shown: None
) -> Delivery:
    """A sent placeholder whose preparation fails."""
    return chosen_delivery


@pytest.fixture
def interrupted_delivery(
    chosen_delivery: Delivery, video_download: mock.AsyncMock, keyboard_already_removed: None
) -> Delivery:
    """A sent placeholder; removing its keyboard will fail; no query started the job."""
    return chosen_delivery


@pytest.fixture
def outage_delivery(
    chosen_delivery: Delivery, video_download: mock.AsyncMock, telegram_outage: None
) -> Delivery:
    """A sent placeholder; replacing its media will fail with a network error."""
    return chosen_delivery


@pytest.fixture
def refresh_callback(
    make_callback: abc.Callable[..., tg.CallbackQuery], saved_link: None, key: str
) -> tg.CallbackQuery:
    """A press of the refresh button of a known link."""
    return make_callback(app.REFRESH_PREFIX + key)


@pytest.fixture
def unknown_refresh_callback(
    make_callback: abc.Callable[..., tg.CallbackQuery], faker: Faker
) -> tg.CallbackQuery:
    """A press of the refresh button of a link that is not stored."""
    return make_callback(app.REFRESH_PREFIX + faker.pystr())


@pytest.fixture
def make_page_callback(
    make_callback: abc.Callable[..., tg.CallbackQuery], saved_link: None, key: str
) -> abc.Callable[[int], tg.CallbackQuery]:
    """Factory `press(page)`: a pager button press for the generated link."""

    def press(page: int) -> tg.CallbackQuery:
        return make_callback(f"{app.PAGE_PREFIX}{key}{spec.PAGE_SEPARATOR}{page}")

    return press


@pytest.fixture
def forgotten_page_callback(
    make_callback: abc.Callable[..., tg.CallbackQuery], faker: Faker
) -> tg.CallbackQuery:
    """A pager press for a post whose link is not stored."""
    return make_callback(f"{app.PAGE_PREFIX}{faker.pystr()}{spec.PAGE_SEPARATOR}{faker.pyint()}")


@pytest.fixture
async def carousel_next_payload(
    cached_photo_carousel: CacheEntries, query: tg.InlineQuery, bot: mock.AsyncMock
) -> str:
    """The next-button data of a carousel cached without a stored link, after one query."""
    await inline.on_inline_query(query, bot)
    answer = Requests(bot).answer
    markup: typing.Any = answer.results[0].reply_markup
    payload: str = markup.inline_keyboard[0][2].callback_data
    return payload


@pytest.fixture
def keyboard_already_removed(bot: mock.AsyncMock, mocker: MockerFixture, faker: Faker) -> None:
    """Removing the keyboard fails: Telegram says there is nothing to change."""
    bot.edit_message_reply_markup.side_effect = exceptions.TelegramBadRequest(
        method=mocker.Mock(), message=faker.sentence()
    )


@pytest.fixture
def telegram_outage(bot: mock.AsyncMock, mocker: MockerFixture, faker: Faker) -> None:
    """Replacing the media fails with a network error."""
    bot.edit_message_media.side_effect = exceptions.TelegramNetworkError(
        method=mocker.Mock(), message=faker.sentence()
    )


@pytest.fixture
def uploading(
    bot: mock.AsyncMock, mocker: MockerFixture, video_file_id: str, faker: Faker
) -> asyncio.Event:
    """Set once an upload started; the upload ends when a status edit hits a flood limit."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_upload(**kwargs: typing.Any) -> typing.Any:
        started.set()
        await release.wait()
        return types.SimpleNamespace(video=types.SimpleNamespace(file_id=video_file_id))

    async def flood(*args: typing.Any, **kwargs: typing.Any) -> None:
        release.set()
        raise exceptions.TelegramRetryAfter(
            method=mocker.Mock(), message=faker.sentence(), retry_after=faker.pyint()
        )

    bot.send_video.side_effect = slow_upload
    bot.edit_message_text.side_effect = flood
    return started


@pytest.fixture
async def flooded_delivery(
    chosen_delivery: Delivery,
    video_download: mock.AsyncMock,
    uploading: asyncio.Event,
    query: tg.InlineQuery,
    bot: mock.AsyncMock,
) -> Delivery:
    """A slow upload is running while every status edit fails with a flood limit."""
    await inline.on_inline_query(query, bot)
    await asyncio.wait_for(uploading.wait(), timeout=spec.PEER_TIMEOUT_SECONDS)
    return chosen_delivery


@pytest.fixture
def single_job_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only one preparation may run at a time."""
    monkeypatch.setattr(inline, "MAX_ACTIVE_JOBS", 1)


@pytest.fixture
async def busy_state(
    slow_download: DownloadGate,
    single_job_limit: None,
    make_inline_query: abc.Callable[..., tg.InlineQuery],
    tiktok_url: str,
    bot: mock.AsyncMock,
) -> None:
    """The only allowed preparation is running; the bot saw nothing since."""
    await inline.on_inline_query(make_inline_query(tiktok_url), bot)
    await asyncio.wait_for(slow_download.started.wait(), timeout=spec.PEER_TIMEOUT_SECONDS)
    bot.reset_mock()


@pytest.fixture
def other_query(
    make_inline_query: abc.Callable[..., tg.InlineQuery], instagram_url: str, busy_state: None
) -> tg.InlineQuery:
    """An inline query for a link other than the one being prepared."""
    return make_inline_query(instagram_url)


type JobOutcome = tuple[int, str, None]


class Credentials(typing.NamedTuple):
    """An Instagram login pair."""

    username: str
    password: str


class ParentJob(typing.NamedTuple):
    """A parent job with the destination and cancel flag it was built from."""

    job: gdl_job.Job
    dest: Path
    cancel: threading.Event


class JobPair(typing.NamedTuple):
    """Two jobs for one URL with different destinations."""

    first: gdl_job.Job
    second: gdl_job.Job
    first_dest: Path
    second_dest: Path


class PartialDownload(typing.NamedTuple):
    """A job that wrote one file and then failed on another."""

    written_name: str
    failed_name: str


class StuckJob:
    """A fake job that waits for the cancel flag, then writes a late file and stops."""

    def __init__(self, late_name: str) -> None:
        self.late_name = late_name
        self.stopped = threading.Event()

    def __call__(self, url: str, work_dir: Path, cancel: threading.Event) -> JobOutcome:
        assert cancel.wait(timeout=spec.GALLERY_JOB_WAIT_SECONDS)
        (work_dir / self.late_name).write_bytes(b"late")
        self.stopped.set()
        return 1, "", None


@pytest.fixture
def cookies_path(download_dir: Path, faker: Faker) -> Path:
    """An existing cookies file."""
    path = download_dir / faker.pystr()
    path.write_text(faker.sentence())
    return path


@pytest.fixture
def cookies_configured(cookies_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The existing cookies file set as `COOKIES_FILE`."""
    monkeypatch.setattr(settings, "COOKIES_FILE", str(cookies_path))
    return cookies_path


@pytest.fixture
def missing_cookies_configured(
    download_dir: Path, faker: Faker, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """A path that does not exist set as `COOKIES_FILE`."""
    path = download_dir / faker.pystr()
    monkeypatch.setattr(settings, "COOKIES_FILE", str(path))
    return path


@pytest.fixture
def credentials(faker: Faker) -> Credentials:
    """A generated login pair."""
    return Credentials(username=faker.pystr(), password=faker.pystr())


@pytest.fixture
def credentials_configured(
    credentials: Credentials, monkeypatch: pytest.MonkeyPatch
) -> Credentials:
    """The login pair set as `INSTAGRAM_USER` and `INSTAGRAM_PASS`."""
    monkeypatch.setattr(settings, "INSTAGRAM_USER", credentials.username)
    monkeypatch.setattr(settings, "INSTAGRAM_PASS", credentials.password)
    return credentials


@pytest.fixture
def partial_credentials_configured(
    credentials: Credentials, monkeypatch: pytest.MonkeyPatch
) -> Credentials:
    """A user name with an empty password in the settings."""
    monkeypatch.setattr(settings, "INSTAGRAM_USER", credentials.username)
    monkeypatch.setattr(settings, "INSTAGRAM_PASS", "")
    return credentials


@pytest.fixture
def credentials_unset_again(
    credentials_configured: Credentials, monkeypatch: pytest.MonkeyPatch
) -> Credentials:
    """Credentials applied to gallery-dl, then the user name cleared in the settings."""
    gdl_job.apply_settings()
    monkeypatch.setattr(settings, "INSTAGRAM_USER", "")
    return credentials_configured


@pytest.fixture
def cancel_event() -> threading.Event:
    """A cancel flag that is not set."""
    return threading.Event()


@pytest.fixture
def set_cancel_event(cancel_event: threading.Event) -> threading.Event:
    """A cancel flag that is already set."""
    cancel_event.set()
    return cancel_event


@pytest.fixture
def job_pair(gallery_dl_url: str, download_dir: Path, faker: Faker) -> JobPair:
    """Two jobs for one URL, each with its own destination."""
    first_dest = download_dir / faker.pystr()
    second_dest = download_dir / faker.pystr()
    return JobPair(
        first=gdl_job.Job(gallery_dl_url, dest=first_dest),
        second=gdl_job.Job(gallery_dl_url, dest=second_dest),
        first_dest=first_dest,
        second_dest=second_dest,
    )


@pytest.fixture
def parent_job(
    gallery_dl_url: str, download_dir: Path, cancel_event: threading.Event
) -> ParentJob:
    """A parent job with its destination and cancel flag."""
    return ParentJob(
        job=gdl_job.Job(gallery_dl_url, dest=download_dir, cancel=cancel_event),
        dest=download_dir,
        cancel=cancel_event,
    )


@pytest.fixture
def media_name(faker: Faker) -> str:
    """A generated video file name."""
    return faker.pystr() + faker.random_element(sorted(app.VIDEO_EXTENSIONS))


@pytest.fixture
def photo_name(faker: Faker) -> str:
    """A generated image file name."""
    return faker.pystr() + faker.random_element(sorted(app.IMAGE_EXTENSIONS))


@pytest.fixture
def job_error(faker: Faker) -> str:
    """A generated gallery-dl error text."""
    return faker.sentence()


@pytest.fixture
def failure_status(faker: Faker) -> int:
    """A non-zero gallery-dl exit status."""
    return faker.pyint(min_value=1, max_value=spec.GALLERY_FAILURE_STATUS_MAX)


@pytest.fixture
def successful_job(mocker: MockerFixture, media_name: str) -> str:
    """`run_job` replaced by a job that writes one video file and succeeds; returns its name."""

    def fake_job(url: str, work_dir: Path, cancel: threading.Event) -> JobOutcome:
        (work_dir / media_name).write_bytes(b"video")
        return 0, "", None

    mocker.patch(spec.GALLERY_RUN_JOB_TARGET, side_effect=fake_job)
    return media_name


@pytest.fixture
def failing_job(
    download_dir: Path, mocker: MockerFixture, failure_status: int, job_error: str
) -> str:
    """`run_job` replaced by a job that fails without files; returns its error text."""
    mocker.patch(spec.GALLERY_RUN_JOB_TARGET, return_value=(failure_status, job_error, None))
    return job_error


@pytest.fixture
def partial_job(
    mocker: MockerFixture, photo_name: str, failure_status: int, faker: Faker
) -> PartialDownload:
    """`run_job` replaced by a job that writes one file and fails on another."""
    failed_name = faker.pystr() + faker.random_element(sorted(app.IMAGE_EXTENSIONS))

    def fake_job(url: str, work_dir: Path, cancel: threading.Event) -> JobOutcome:
        (work_dir / photo_name).write_bytes(b"photo")
        return failure_status, f"{faker.sentence()} {failed_name}", None

    mocker.patch(spec.GALLERY_RUN_JOB_TARGET, side_effect=fake_job)
    return PartialDownload(written_name=photo_name, failed_name=failed_name)


@pytest.fixture
def stuck_job(mocker: MockerFixture, media_name: str, monkeypatch: pytest.MonkeyPatch) -> StuckJob:
    """`run_job` replaced by a job that only stops once cancelled; the timeout is tiny."""
    monkeypatch.setattr(settings, "DOWNLOAD_TIMEOUT", spec.GALLERY_JOB_TIMEOUT_SECONDS)
    job = StuckJob(media_name)
    mocker.patch(spec.GALLERY_RUN_JOB_TARGET, side_effect=job)
    return job


@pytest.fixture
def timed_out_download(
    stuck_job: StuckJob, mocker: MockerFixture, gallery_dl_url: str
) -> abc.Callable[[], abc.Awaitable[gallery.DownloadResult]]:
    """Awaiting the result downloads with the stuck job, then waits for the work dir removal."""
    removed = asyncio.Event()

    def remove_and_signal(directory: Path, *, ignore_errors: bool) -> None:
        rmtree(directory, ignore_errors=ignore_errors)
        removed.set()

    mocker.patch(spec.GALLERY_RMTREE_TARGET, side_effect=remove_and_signal)

    async def run() -> gallery.DownloadResult:
        outcome = await gallery.download_media(gallery_dl_url)
        await asyncio.wait_for(removed.wait(), timeout=spec.GALLERY_CLEANUP_WAIT_SECONDS)
        return outcome

    return run


@pytest.fixture
def remove_tree(mocker: MockerFixture) -> mock.MagicMock:
    """`shutil.rmtree` as seen by the gallery module, replaced by a mock."""
    return mocker.patch(spec.GALLERY_RMTREE_TARGET)


@pytest.fixture(params=("existing", "missing"))
def cleanup_target(request: pytest.FixtureRequest, download_dir: Path, faker: Faker) -> Path:
    """An existing directory, then one that does not exist."""
    if request.param == "existing":
        return download_dir
    return download_dir / faker.pystr()


@pytest.fixture
def execute(mocker: MockerFixture) -> mock.MagicMock:
    """`Job.execute` replaced by a mock, to see whether the site would be contacted."""
    return mocker.patch.object(gdl_job.Job, "execute")


class Telegram:
    """Records every method the bound message sends through the bot and answers like Telegram."""

    def __init__(self, status: mock.AsyncMock) -> None:
        self.status = status
        self.methods: list[methods.TelegramMethod[typing.Any]] = []

    def edited_text(self) -> str:
        """The text the status message was last edited to."""
        last_call = self.status.edit_text.call_args
        return str(last_call.args[0])

    def kinds(self) -> list[type]:
        """Types of the sent methods, in the order of sending."""
        return [type(method) for method in self.methods]

    def sent_files(self) -> list[tuple[type, typing.Any]]:
        """Pairs of (method type, file argument) for every sent video and photo."""
        return [
            (type(method), method.video if isinstance(method, methods.SendVideo) else method.photo)
            for method in self.methods
            if isinstance(method, methods.SendVideo | methods.SendPhoto)
        ]


class DeliveryCase(typing.NamedTuple):
    """A successful download of one file with what must be sent and cached for it."""

    download: mock.AsyncMock
    work_dir: Path
    method_type: type
    cache_item: dict[str, str]


class CachedLink(typing.NamedTuple):
    """A link whose media is already cached, and the download that must stay unused."""

    download: mock.AsyncMock
    expected_files: list[tuple[type, str]]


class FailedDownload(typing.NamedTuple):
    """A failed download whose error needs escaping and shortening."""

    escaped_start: str


class LinkPair(typing.NamedTuple):
    """A message carrying two links, and the links in the order of appearance."""

    message: tg.Message
    urls: list[str]


@pytest.fixture
def timer() -> StageTimer:
    """A fresh stage timer."""
    return StageTimer()


@pytest.fixture
def telegram(
    bot: mock.AsyncMock, mocker: MockerFixture, video_file_id: str, photo_file_id: str
) -> Telegram:
    """Make the bot answer sent methods: a status message, then video and photo with file ids."""
    recorder = Telegram(mocker.AsyncMock())

    async def respond(method: methods.TelegramMethod[typing.Any]) -> typing.Any:
        recorder.methods.append(method)
        if isinstance(method, methods.SendVideo):
            return types.SimpleNamespace(video=types.SimpleNamespace(file_id=video_file_id))
        if isinstance(method, methods.SendPhoto):
            return types.SimpleNamespace(photo=[types.SimpleNamespace(file_id=photo_file_id)])
        if isinstance(method, methods.SendMessage):
            return recorder.status
        return True

    bot.side_effect = respond
    return recorder


@pytest.fixture
def link_message(make_message: abc.Callable[..., tg.Message], supported_url: str) -> tg.Message:
    """A bound message whose text is the supported link."""
    return make_message(supported_url)


@pytest.fixture
def unbound_message(make_message: abc.Callable[..., tg.Message], supported_url: str) -> tg.Message:
    """A message with a link that is not bound to any bot."""
    return make_message(supported_url, bound=False)


@pytest.fixture
def textless_message(make_message: abc.Callable[..., tg.Message]) -> tg.Message:
    """A bound message without text."""
    return make_message()


@pytest.fixture
def own_placeholder_message(
    make_message: abc.Callable[..., tg.Message], bot: mock.AsyncMock, supported_url: str
) -> tg.Message:
    """The placeholder this bot's own inline mode sends: status and link, `via_bot` is the bot."""
    text = app.STATUS_TEMPLATE.format(status=app.TEXT_DOWNLOADING, url=supported_url)
    return make_message(text, via_bot=factories.UserFactory.build(id=bot.id))


@pytest.fixture
def foreign_via_message(
    make_message: abc.Callable[..., tg.Message], supported_url: str
) -> tg.Message:
    """A message with a link sent through someone else's inline bot."""
    return make_message(supported_url, via_bot=factories.UserFactory.build())


@pytest.fixture
def two_link_message(
    make_message: abc.Callable[..., tg.Message], tiktok_url: str, instagram_url: str
) -> LinkPair:
    """A bound message with a TikTok link followed by an Instagram link."""
    return LinkPair(make_message(f"{tiktok_url} {instagram_url}"), [tiktok_url, instagram_url])


@pytest.fixture
def process_url(mocker: MockerFixture) -> mock.AsyncMock:
    """Replace `_process_url` of the media handler."""
    replacement: mock.AsyncMock = mocker.AsyncMock()
    mocker.patch("handlers.media._process_url", new=replacement)
    return replacement


@pytest.fixture
def serve_download(
    mocker: MockerFixture, database_ready: Path
) -> abc.Callable[[gallery.DownloadResult], mock.AsyncMock]:
    """Factory: replace the downloader of the delivery module so it returns the given result.

    Requests the temporary database, because every delivery looks the link up in the cache.
    """

    def serve(outcome: gallery.DownloadResult) -> mock.AsyncMock:
        download: mock.AsyncMock = mocker.AsyncMock(return_value=outcome)
        mocker.patch.object(delivery, "download_media", new=download)
        return download

    return serve


@pytest.fixture(params=[True, False], ids=["video", "photo"])
def is_video(request: pytest.FixtureRequest) -> bool:
    """Whether the downloaded file is a video; the test runs once per kind."""
    return bool(request.param)


@pytest.fixture
def chat_work_dir(tmp_path: Path, faker: Faker) -> Path:
    """An existing work directory of a download."""
    directory = tmp_path / faker.pystr()
    directory.mkdir()
    return directory


@pytest.fixture
def work_file(chat_work_dir: Path, faker: Faker) -> Path:
    """A small non-empty file inside the work directory."""
    path = chat_work_dir / faker.pystr()
    size = faker.pyint(min_value=1, max_value=64)
    path.write_bytes(faker.binary(length=size))
    return path


@pytest.fixture
def cache_item(is_video: bool, video_file_id: str, photo_file_id: str) -> dict[str, str]:
    """The cache entry that sending the file must produce."""
    if is_video:
        return {app.KEY_TYPE: app.TYPE_VIDEO, app.KEY_FILE_ID: video_file_id}
    return {app.KEY_TYPE: app.TYPE_PHOTO, app.KEY_FILE_ID: photo_file_id}


@pytest.fixture
def delivery_case(
    is_video: bool,
    chat_work_dir: Path,
    work_file: Path,
    cache_item: dict[str, str],
    serve_download: abc.Callable[[gallery.DownloadResult], mock.AsyncMock],
) -> DeliveryCase:
    """A successful download of one video or one photo kept in its own work directory."""
    media_file = factories.MediaFileFactory.build(path=work_file, is_video=is_video)
    outcome = factories.DownloadResultFactory.build(
        media_files=[media_file], work_dir=chat_work_dir
    )
    method_type = methods.SendVideo if is_video else methods.SendPhoto
    return DeliveryCase(serve_download(outcome), chat_work_dir, method_type, cache_item)


@pytest.fixture
async def cached_link(
    serve_download: abc.Callable[[gallery.DownloadResult], mock.AsyncMock],
    database_ready: Path,
    supported_url: str,
    video_file_id: str,
    photo_file_id: str,
) -> CachedLink:
    """Cache a video and a photo for the link; a download would return an empty result."""
    await database.set_cached_media(
        supported_url,
        [
            {app.KEY_TYPE: app.TYPE_VIDEO, app.KEY_FILE_ID: video_file_id},
            {app.KEY_TYPE: app.TYPE_PHOTO, app.KEY_FILE_ID: photo_file_id},
        ],
    )
    return CachedLink(
        download=serve_download(factories.DownloadResultFactory.build()),
        expected_files=[(methods.SendVideo, video_file_id), (methods.SendPhoto, photo_file_id)],
    )


@pytest.fixture
def failed_download(
    serve_download: abc.Callable[[gallery.DownloadResult], mock.AsyncMock], faker: Faker
) -> FailedDownload:
    """A failed download whose error holds markup characters and is far over the length limit."""
    word = faker.word()
    start = f"{spec.HTML_LT}{word}{spec.HTML_GT} {spec.HTML_AMP} "
    length = app.ERROR_TEXT_LIMIT * 10
    error = start + faker.pystr(min_chars=length, max_chars=length)
    serve_download(factories.DownloadResultFactory.build(success=False, error=error))
    return FailedDownload(
        escaped_start=(
            f"{spec.HTML_LT_ESCAPED}{word}{spec.HTML_GT_ESCAPED} {spec.HTML_AMP_ESCAPED} "
        )
    )


type FileMaker = abc.Callable[[Path, str], Path]


class Library(typing.NamedTuple):
    """A directory together with the (path, is_video) pairs expected to be collected from it."""

    directory: Path
    expected: set[tuple[Path, bool]]


@pytest.fixture(params=sorted(app.VIDEO_EXTENSIONS))
def video_extension(request: pytest.FixtureRequest) -> str:
    """Every supported video extension, one test run per extension."""
    return str(request.param)


@pytest.fixture(params=sorted(app.IMAGE_EXTENSIONS))
def image_extension(request: pytest.FixtureRequest) -> str:
    """Every supported image extension, one test run per extension."""
    return str(request.param)


@pytest.fixture(params=sorted(app.VIDEO_EXTENSIONS | app.IMAGE_EXTENSIONS))
def supported_extension(request: pytest.FixtureRequest) -> str:
    """Every supported extension, video or image, one test run per extension."""
    return str(request.param)


@pytest.fixture(params=sorted(spec.FOREIGN_EXTENSIONS))
def foreign_extension(request: pytest.FixtureRequest) -> str:
    """Every extension the collector must ignore, one test run per extension."""
    return str(request.param)


@pytest.fixture
def library_dir(tmp_path: Path, faker: Faker) -> Path:
    """A new empty directory with a generated name."""
    directory = tmp_path / faker.pystr(
        min_chars=spec.COLLECT_NAME_MIN_CHARS, max_chars=spec.COLLECT_NAME_MAX_CHARS
    )
    directory.mkdir()
    return directory


@pytest.fixture
def make_file(faker: Faker) -> FileMaker:
    """Create a file with a generated name and content, given a directory and an extension."""

    def factory(directory: Path, extension: str) -> Path:
        name = faker.pystr(
            min_chars=spec.COLLECT_NAME_MIN_CHARS, max_chars=spec.COLLECT_NAME_MAX_CHARS
        )
        path = directory / f"{name}{extension}"
        path.write_bytes(faker.binary(length=spec.COLLECT_CONTENT_LENGTH))
        return path

    return factory


@pytest.fixture
def empty_library(library_dir: Path) -> Library:
    """A directory without any file."""
    return Library(directory=library_dir, expected=set())


@pytest.fixture
def mixed_library(
    library_dir: Path, make_file: FileMaker, video_extension: str, image_extension: str
) -> Library:
    """One video, one image and one unrelated file."""
    video = make_file(library_dir, video_extension)
    image = make_file(library_dir, image_extension)
    make_file(library_dir, min(spec.FOREIGN_EXTENSIONS))
    return Library(directory=library_dir, expected={(video, True), (image, False)})


@pytest.fixture
def nested_library(
    library_dir: Path,
    make_file: FileMaker,
    video_extension: str,
    image_extension: str,
    faker: Faker,
) -> Library:
    """A video in a sub-directory two levels deep and an image at the top."""
    nested = library_dir / faker.pystr() / faker.pystr()
    nested.mkdir(parents=True)
    video = make_file(nested, video_extension)
    image = make_file(library_dir, image_extension)
    return Library(directory=library_dir, expected={(video, True), (image, False)})


@pytest.fixture
def single_library(library_dir: Path, make_file: FileMaker, supported_extension: str) -> Library:
    """One file with the given supported extension, classified by the app's constants."""
    path = make_file(library_dir, supported_extension)
    return Library(
        directory=library_dir, expected={(path, supported_extension in app.VIDEO_EXTENSIONS)}
    )


@pytest.fixture
def full_library(library_dir: Path, make_file: FileMaker) -> Library:
    """One file per supported extension."""
    videos = {(make_file(library_dir, extension), True) for extension in app.VIDEO_EXTENSIONS}
    images = {(make_file(library_dir, extension), False) for extension in app.IMAGE_EXTENSIONS}
    return Library(directory=library_dir, expected=videos | images)


@pytest.fixture
def foreign_library(library_dir: Path, make_file: FileMaker, foreign_extension: str) -> Library:
    """One file with an unsupported extension; nothing is expected."""
    make_file(library_dir, foreign_extension)
    return Library(directory=library_dir, expected=set())


@pytest.fixture
def shouting_library(
    library_dir: Path, make_file: FileMaker, video_extension: str, image_extension: str
) -> Library:
    """A video and an image whose extensions are written in upper case."""
    video = make_file(library_dir, video_extension.upper())
    image = make_file(library_dir, image_extension.upper())
    return Library(directory=library_dir, expected={(video, True), (image, False)})


@pytest.fixture
def media_file() -> gallery.MediaFile:
    """A generated media file."""
    return factories.MediaFileFactory.build()


@pytest.fixture
def other_path(faker: Faker) -> Path:
    """A path different from the one of `media_file`."""
    return Path(
        faker.pystr(min_chars=spec.COLLECT_NAME_MIN_CHARS, max_chars=spec.COLLECT_NAME_MAX_CHARS)
    )


@pytest.fixture
def entry_point() -> metadata.EntryPoint:
    """The console entry point of the installed distribution."""
    return next(
        point
        for point in metadata.distribution(spec.DISTRIBUTION_NAME).entry_points
        if point.name == spec.ENTRY_POINT_NAME
    )


@pytest.fixture
def entry_module(entry_point: metadata.EntryPoint) -> types.ModuleType:
    """The module the entry point lives in, imported."""
    return import_module(entry_point.module)
