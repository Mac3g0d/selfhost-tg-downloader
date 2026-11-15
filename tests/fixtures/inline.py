"""Fixtures for the inline mode tests."""

import asyncio
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple
from unittest.mock import AsyncMock

import pytest
from aiogram import exceptions, methods
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    InlineKeyboardButton,
    InlineQuery,
)
from faker import Faker
from pytest_mock import MockerFixture

from config import settings
from constants import (
    KEY_FILE_ID,
    KEY_TYPE,
    PAGE_PREFIX,
    PLACEHOLDER_PREFIX,
    REFRESH_PREFIX,
    TYPE_PHOTO,
    TYPE_VIDEO,
)
from database import save_inline_link, set_cached_media
from downloader.gallery import MediaFile
from handlers import inline
from handlers import inline_ui as ui
from tests.constants import (
    HTML_GT,
    HTML_GT_ESCAPED,
    HTML_LT,
    HTML_LT_ESCAPED,
    PAGE_SEPARATOR,
    PEER_TIMEOUT_SECONDS,
)
from tests.factories import DownloadResultFactory


def _first_row(markup: Any) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = markup.inline_keyboard[0]
    return row


class DownloadGate:
    """A download that starts, then blocks until `release` is set; it ends as a failure."""

    def __init__(self, download: AsyncMock) -> None:
        self.download = download
        self.started = asyncio.Event()
        self.release = asyncio.Event()


class FailingDownload:
    """A failing download with a reason that needs HTML escaping, and its escaped form."""

    def __init__(self, download: AsyncMock, reason: str, escaped: str) -> None:
        self.download = download
        self.reason = reason
        self.escaped = escaped


class Requests:
    """The API requests the bot double received, as method objects."""

    def __init__(self, bot: AsyncMock) -> None:
        self.bot = bot

    @property
    def sent(self) -> list[Any]:
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

    def first_row(self, markup: Any) -> list[InlineKeyboardButton]:
        """The first row of buttons of a keyboard."""
        return _first_row(markup)


class Edits:
    """The message edits the bot double received."""

    def __init__(self, bot: AsyncMock) -> None:
        self.bot = bot

    @property
    def edited_media(self) -> Any:
        """The media object of the last media edit."""
        call = self.bot.edit_message_media.call_args
        return call.args[0]

    @property
    def edited_kwargs(self) -> dict[str, Any]:
        """The keyword arguments of the last media edit."""
        call = self.bot.edit_message_media.call_args
        kwargs: dict[str, Any] = call.kwargs
        return kwargs

    @property
    def edited_row(self) -> list[InlineKeyboardButton]:
        """The first keyboard row of the last media edit."""
        return _first_row(self.edited_kwargs["reply_markup"])

    @property
    def status_text(self) -> str:
        """The text of the last status edit."""
        call = self.bot.edit_message_text.call_args
        text: str = call.args[0]
        return text

    @property
    def status_button(self) -> InlineKeyboardButton:
        """The first button of the last status edit."""
        call = self.bot.edit_message_text.call_args
        return _first_row(call.kwargs["reply_markup"])[0]

    @property
    def status_texts(self) -> list[str]:
        """The texts of all status edits."""
        return [call.args[0] for call in self.bot.edit_message_text.call_args_list]


class Delivery(NamedTuple):
    """A sent placeholder of the generated link, ready to be replaced with the media."""

    chosen: ChosenInlineResult
    url: str
    key: str
    inline_message_id: str
    work_dir: Path


@pytest.fixture(autouse=True)
async def _inline_env(database_ready: Path, faker: Faker) -> AsyncGenerator[None]:
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
def requests(bot: AsyncMock) -> Requests:
    """The requests received by the bot double."""
    return Requests(bot)


@pytest.fixture
def edits(bot: AsyncMock) -> Edits:
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
) -> Callable[..., AsyncMock]:
    """Factory `stage(*is_video)`: patches `download_media` to produce those files on disk."""

    def stage(*kinds: bool) -> AsyncMock:
        def make(url: str) -> Any:
            work_dir.mkdir(exist_ok=True)
            files = []
            for is_video in kinds:
                path = work_dir / faker.pystr()
                path.write_bytes(faker.binary(length=8))
                files.append(MediaFile(path=path, is_video=is_video))
            return DownloadResultFactory.build(media_files=files, work_dir=work_dir)

        return mocker.patch.object(inline, "download_media", side_effect=make)

    return stage


@pytest.fixture
def video_download(stage_download: Callable[..., AsyncMock]) -> AsyncMock:
    """A download that yields one video file."""
    return stage_download(True)


@pytest.fixture
def carousel_download(stage_download: Callable[..., AsyncMock]) -> AsyncMock:
    """A download that yields two photos."""
    return stage_download(False, False)


@pytest.fixture
def slow_download(mocker: MockerFixture, faker: Faker) -> DownloadGate:
    """A download that blocks on `release` and then fails."""
    gate = DownloadGate(mocker.AsyncMock())

    async def block(url: str) -> Any:
        gate.started.set()
        await gate.release.wait()
        return DownloadResultFactory.build(success=False, error=faker.sentence())

    gate.download = mocker.patch.object(inline, "download_media", side_effect=block)
    return gate


@pytest.fixture
def failing_download(mocker: MockerFixture, faker: Faker) -> FailingDownload:
    """A download failing with a reason that contains angle brackets."""
    word = faker.pystr()
    reason = f"{HTML_LT}{word}{HTML_GT}"
    escaped = f"{HTML_LT_ESCAPED}{word}{HTML_GT_ESCAPED}"
    download = mocker.patch.object(
        inline,
        "download_media",
        return_value=DownloadResultFactory.build(success=False, error=reason),
    )
    return FailingDownload(download, reason, escaped)


@pytest.fixture
def make_cached(faker: Faker, supported_url: str) -> Callable[..., Any]:
    """Async factory `cache(*kinds)`: stores entries of those types and returns them."""

    async def cache(*kinds: str) -> list[dict[str, str]]:
        entries = [{KEY_TYPE: kind, KEY_FILE_ID: faker.pystr()} for kind in kinds]
        await set_cached_media(supported_url, entries)
        return entries

    return cache


@pytest.fixture
async def saved_link(supported_url: str, key: str) -> None:
    """The link stored under its key, as after an inline query."""
    await save_inline_link(key, supported_url)


@pytest.fixture
async def cached_video(make_cached: Callable[..., Any]) -> list[dict[str, str]]:
    """One cached video."""
    entries: list[dict[str, str]] = await make_cached(TYPE_VIDEO)
    return entries


@pytest.fixture
async def cached_photo(make_cached: Callable[..., Any]) -> list[dict[str, str]]:
    """One cached photo."""
    entries: list[dict[str, str]] = await make_cached(TYPE_PHOTO)
    return entries


@pytest.fixture
async def cached_mixed_carousel(make_cached: Callable[..., Any]) -> list[dict[str, str]]:
    """A cached photo followed by a cached video."""
    entries: list[dict[str, str]] = await make_cached(TYPE_PHOTO, TYPE_VIDEO)
    return entries


@pytest.fixture
async def cached_photo_carousel(make_cached: Callable[..., Any]) -> list[dict[str, str]]:
    """Two cached photos."""
    entries: list[dict[str, str]] = await make_cached(TYPE_PHOTO, TYPE_PHOTO)
    return entries


@pytest.fixture
def query(make_inline_query: Callable[..., InlineQuery], supported_url: str) -> InlineQuery:
    """An inline query with the generated link."""
    return make_inline_query(supported_url)


@pytest.fixture
async def placeholder_shown(query: InlineQuery, bot: AsyncMock) -> None:
    """One inline query was answered with the placeholder."""
    await inline.on_inline_query(query, bot)


@pytest.fixture
async def placeholder_shown_twice(
    placeholder_shown: None,
    make_inline_query: Callable[..., InlineQuery],
    supported_url: str,
    bot: AsyncMock,
) -> None:
    """A second inline query for the same link was answered too."""
    await inline.on_inline_query(make_inline_query(supported_url), bot)


@pytest.fixture
def chosen_delivery(
    make_chosen_result: Callable[..., ChosenInlineResult],
    saved_link: None,
    key: str,
    supported_url: str,
    work_dir: Path,
) -> Delivery:
    """The user sent the placeholder of the generated link; no preparation has started."""
    chosen = make_chosen_result(PLACEHOLDER_PREFIX + key, query=supported_url)
    assert chosen.inline_message_id is not None
    return Delivery(chosen, supported_url, key, chosen.inline_message_id, work_dir)


@pytest.fixture
def video_delivery(
    chosen_delivery: Delivery, video_download: AsyncMock, placeholder_shown: None
) -> Delivery:
    """A sent placeholder whose preparation (one video) was started by an inline query."""
    return chosen_delivery


@pytest.fixture
def carousel_delivery(
    chosen_delivery: Delivery, carousel_download: AsyncMock, placeholder_shown: None
) -> Delivery:
    """A sent placeholder whose preparation (two photos) was started by an inline query."""
    return chosen_delivery


@pytest.fixture
def shared_delivery(
    chosen_delivery: Delivery, video_download: AsyncMock, placeholder_shown_twice: None
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
    chosen_delivery: Delivery, video_download: AsyncMock, keyboard_already_removed: None
) -> Delivery:
    """A sent placeholder; removing its keyboard will fail; no query started the job."""
    return chosen_delivery


@pytest.fixture
def outage_delivery(
    chosen_delivery: Delivery, video_download: AsyncMock, telegram_outage: None
) -> Delivery:
    """A sent placeholder; replacing its media will fail with a network error."""
    return chosen_delivery


@pytest.fixture
def refresh_callback(
    make_callback: Callable[..., CallbackQuery], saved_link: None, key: str
) -> CallbackQuery:
    """A press of the refresh button of a known link."""
    return make_callback(REFRESH_PREFIX + key)


@pytest.fixture
def unknown_refresh_callback(
    make_callback: Callable[..., CallbackQuery], faker: Faker
) -> CallbackQuery:
    """A press of the refresh button of a link that is not stored."""
    return make_callback(REFRESH_PREFIX + faker.pystr())


@pytest.fixture
def make_page_callback(
    make_callback: Callable[..., CallbackQuery], saved_link: None, key: str
) -> Callable[[int], CallbackQuery]:
    """Factory `press(page)`: a pager button press for the generated link."""

    def press(page: int) -> CallbackQuery:
        return make_callback(f"{PAGE_PREFIX}{key}{PAGE_SEPARATOR}{page}")

    return press


@pytest.fixture
def forgotten_page_callback(
    make_callback: Callable[..., CallbackQuery], faker: Faker
) -> CallbackQuery:
    """A pager press for a post whose link is not stored."""
    return make_callback(f"{PAGE_PREFIX}{faker.pystr()}{PAGE_SEPARATOR}{faker.pyint()}")


@pytest.fixture
async def carousel_next_payload(
    cached_photo_carousel: list[dict[str, str]], query: InlineQuery, bot: AsyncMock
) -> str:
    """The next-button data of a carousel cached without a stored link, after one query."""
    await inline.on_inline_query(query, bot)
    answer = Requests(bot).answer
    markup: Any = answer.results[0].reply_markup
    payload: str = markup.inline_keyboard[0][2].callback_data
    return payload


@pytest.fixture
def keyboard_already_removed(bot: AsyncMock, mocker: MockerFixture, faker: Faker) -> None:
    """Removing the keyboard fails: Telegram says there is nothing to change."""
    bot.edit_message_reply_markup.side_effect = exceptions.TelegramBadRequest(
        method=mocker.Mock(), message=faker.sentence()
    )


@pytest.fixture
def telegram_outage(bot: AsyncMock, mocker: MockerFixture, faker: Faker) -> None:
    """Replacing the media fails with a network error."""
    bot.edit_message_media.side_effect = exceptions.TelegramNetworkError(
        method=mocker.Mock(), message=faker.sentence()
    )


@pytest.fixture
def uploading(
    bot: AsyncMock, mocker: MockerFixture, video_file_id: str, faker: Faker
) -> asyncio.Event:
    """Set once an upload started; the upload ends when a status edit hits a flood limit."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_upload(**kwargs: Any) -> Any:
        started.set()
        await release.wait()
        return SimpleNamespace(video=SimpleNamespace(file_id=video_file_id))

    async def flood(*args: Any, **kwargs: Any) -> None:
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
    video_download: AsyncMock,
    uploading: asyncio.Event,
    query: InlineQuery,
    bot: AsyncMock,
) -> Delivery:
    """A slow upload is running while every status edit fails with a flood limit."""
    await inline.on_inline_query(query, bot)
    await asyncio.wait_for(uploading.wait(), timeout=PEER_TIMEOUT_SECONDS)
    return chosen_delivery


@pytest.fixture
def single_job_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only one preparation may run at a time."""
    monkeypatch.setattr(inline, "MAX_ACTIVE_JOBS", 1)


@pytest.fixture
async def busy_state(
    slow_download: DownloadGate,
    single_job_limit: None,
    make_inline_query: Callable[..., InlineQuery],
    tiktok_url: str,
    bot: AsyncMock,
) -> None:
    """The only allowed preparation is running; the bot saw nothing since."""
    await inline.on_inline_query(make_inline_query(tiktok_url), bot)
    await asyncio.wait_for(slow_download.started.wait(), timeout=PEER_TIMEOUT_SECONDS)
    bot.reset_mock()


@pytest.fixture
def other_query(
    make_inline_query: Callable[..., InlineQuery], instagram_url: str, busy_state: None
) -> InlineQuery:
    """An inline query for a link other than the one being prepared."""
    return make_inline_query(instagram_url)
