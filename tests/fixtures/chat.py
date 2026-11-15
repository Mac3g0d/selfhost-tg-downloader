"""Fixtures for the chat message and delivery tests."""

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple
from unittest.mock import AsyncMock

import pytest
from aiogram.methods import SendMessage, SendPhoto, SendVideo, TelegramMethod
from aiogram.types import Message
from faker import Faker
from pytest_mock import MockerFixture

import database
from constants import (
    ERROR_TEXT_LIMIT,
    KEY_FILE_ID,
    KEY_TYPE,
    STATUS_TEMPLATE,
    TEXT_DOWNLOADING,
    TYPE_PHOTO,
    TYPE_VIDEO,
)
from downloader.gallery import DownloadResult
from handlers import delivery
from tests.constants import (
    HTML_AMP,
    HTML_AMP_ESCAPED,
    HTML_GT,
    HTML_GT_ESCAPED,
    HTML_LT,
    HTML_LT_ESCAPED,
)
from tests.factories import DownloadResultFactory, MediaFileFactory, UserFactory
from timing import StageTimer


class Telegram:
    """Records every method the bound message sends through the bot and answers like Telegram."""

    def __init__(self, status: AsyncMock) -> None:
        self.status = status
        self.methods: list[TelegramMethod[Any]] = []

    def edited_text(self) -> str:
        """The text the status message was last edited to."""
        last_call = self.status.edit_text.call_args
        return str(last_call.args[0])

    def kinds(self) -> list[type]:
        """Types of the sent methods, in the order of sending."""
        return [type(method) for method in self.methods]

    def sent_files(self) -> list[tuple[type, Any]]:
        """Pairs of (method type, file argument) for every sent video and photo."""
        return [
            (type(method), method.video if isinstance(method, SendVideo) else method.photo)
            for method in self.methods
            if isinstance(method, SendVideo | SendPhoto)
        ]


class DeliveryCase(NamedTuple):
    """A successful download of one file with what must be sent and cached for it."""

    download: AsyncMock
    work_dir: Path
    method_type: type
    cache_item: dict[str, str]


class CachedLink(NamedTuple):
    """A link whose media is already cached, and the download that must stay unused."""

    download: AsyncMock
    expected_files: list[tuple[type, str]]


class FailedDownload(NamedTuple):
    """A failed download whose error needs escaping and shortening."""

    escaped_start: str


class LinkPair(NamedTuple):
    """A message carrying two links, and the links in the order of appearance."""

    message: Message
    urls: list[str]


@pytest.fixture
def timer() -> StageTimer:
    """A fresh stage timer."""
    return StageTimer()


@pytest.fixture
def telegram(
    bot: AsyncMock, mocker: MockerFixture, video_file_id: str, photo_file_id: str
) -> Telegram:
    """Make the bot answer sent methods: a status message, then video and photo with file ids."""
    recorder = Telegram(mocker.AsyncMock())

    async def respond(method: TelegramMethod[Any]) -> Any:
        recorder.methods.append(method)
        if isinstance(method, SendVideo):
            return SimpleNamespace(video=SimpleNamespace(file_id=video_file_id))
        if isinstance(method, SendPhoto):
            return SimpleNamespace(photo=[SimpleNamespace(file_id=photo_file_id)])
        if isinstance(method, SendMessage):
            return recorder.status
        return True

    bot.side_effect = respond
    return recorder


@pytest.fixture
def link_message(make_message: Callable[..., Message], supported_url: str) -> Message:
    """A bound message whose text is the supported link."""
    return make_message(supported_url)


@pytest.fixture
def unbound_message(make_message: Callable[..., Message], supported_url: str) -> Message:
    """A message with a link that is not bound to any bot."""
    return make_message(supported_url, bound=False)


@pytest.fixture
def textless_message(make_message: Callable[..., Message]) -> Message:
    """A bound message without text."""
    return make_message()


@pytest.fixture
def own_placeholder_message(
    make_message: Callable[..., Message], bot: AsyncMock, supported_url: str
) -> Message:
    """The placeholder this bot's own inline mode sends: status and link, `via_bot` is the bot."""
    text = STATUS_TEMPLATE.format(status=TEXT_DOWNLOADING, url=supported_url)
    return make_message(text, via_bot=UserFactory.build(id=bot.id))


@pytest.fixture
def foreign_via_message(make_message: Callable[..., Message], supported_url: str) -> Message:
    """A message with a link sent through someone else's inline bot."""
    return make_message(supported_url, via_bot=UserFactory.build())


@pytest.fixture
def two_links(
    make_message: Callable[..., Message], tiktok_url: str, instagram_url: str
) -> LinkPair:
    """A bound message with a TikTok link followed by an Instagram link."""
    return LinkPair(make_message(f"{tiktok_url} {instagram_url}"), [tiktok_url, instagram_url])


@pytest.fixture
def process_url(mocker: MockerFixture) -> AsyncMock:
    """Replace `_process_url` of the media handler."""
    replacement: AsyncMock = mocker.AsyncMock()
    mocker.patch("handlers.media._process_url", new=replacement)
    return replacement


@pytest.fixture
def serve_download(
    mocker: MockerFixture, database_ready: Path
) -> Callable[[DownloadResult], AsyncMock]:
    """Factory: replace the downloader of the delivery module so it returns the given result.

    Requests the temporary database, because every delivery looks the link up in the cache.
    """

    def serve(outcome: DownloadResult) -> AsyncMock:
        download: AsyncMock = mocker.AsyncMock(return_value=outcome)
        mocker.patch.object(delivery, "download_media", new=download)
        return download

    return serve


@pytest.fixture(params=[True, False], ids=["video", "photo"])
def is_video(request: pytest.FixtureRequest) -> bool:
    """Whether the downloaded file is a video; the test runs once per kind."""
    return bool(request.param)


@pytest.fixture
def work_dir(tmp_path: Path, faker: Faker) -> Path:
    """An existing work directory of a download."""
    directory = tmp_path / faker.pystr()
    directory.mkdir()
    return directory


@pytest.fixture
def work_file(work_dir: Path, faker: Faker) -> Path:
    """A small non-empty file inside the work directory."""
    path = work_dir / faker.pystr()
    size = faker.pyint(min_value=1, max_value=64)
    path.write_bytes(faker.binary(length=size))
    return path


@pytest.fixture
def cache_item(is_video: bool, video_file_id: str, photo_file_id: str) -> dict[str, str]:
    """The cache entry that sending the file must produce."""
    if is_video:
        return {KEY_TYPE: TYPE_VIDEO, KEY_FILE_ID: video_file_id}
    return {KEY_TYPE: TYPE_PHOTO, KEY_FILE_ID: photo_file_id}


@pytest.fixture
def delivery_case(
    is_video: bool,
    work_dir: Path,
    work_file: Path,
    cache_item: dict[str, str],
    serve_download: Callable[[DownloadResult], AsyncMock],
) -> DeliveryCase:
    """A successful download of one video or one photo kept in its own work directory."""
    media_file = MediaFileFactory.build(path=work_file, is_video=is_video)
    outcome = DownloadResultFactory.build(media_files=[media_file], work_dir=work_dir)
    method_type = SendVideo if is_video else SendPhoto
    return DeliveryCase(serve_download(outcome), work_dir, method_type, cache_item)


@pytest.fixture
async def cached_link(
    serve_download: Callable[[DownloadResult], AsyncMock],
    database_ready: Path,
    supported_url: str,
    video_file_id: str,
    photo_file_id: str,
) -> CachedLink:
    """Cache a video and a photo for the link; a download would return an empty result."""
    await database.set_cached_media(
        supported_url,
        [
            {KEY_TYPE: TYPE_VIDEO, KEY_FILE_ID: video_file_id},
            {KEY_TYPE: TYPE_PHOTO, KEY_FILE_ID: photo_file_id},
        ],
    )
    return CachedLink(
        download=serve_download(DownloadResultFactory.build()),
        expected_files=[(SendVideo, video_file_id), (SendPhoto, photo_file_id)],
    )


@pytest.fixture
def failed_download(
    serve_download: Callable[[DownloadResult], AsyncMock], faker: Faker
) -> FailedDownload:
    """A failed download whose error holds markup characters and is far over the length limit."""
    word = faker.word()
    start = f"{HTML_LT}{word}{HTML_GT} {HTML_AMP} "
    length = ERROR_TEXT_LIMIT * 10
    error = start + faker.pystr(min_chars=length, max_chars=length)
    serve_download(DownloadResultFactory.build(success=False, error=error))
    return FailedDownload(
        escaped_start=f"{HTML_LT_ESCAPED}{word}{HTML_GT_ESCAPED} {HTML_AMP_ESCAPED} "
    )
