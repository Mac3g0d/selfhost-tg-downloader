"""Core fixtures: isolated settings, generated scalars, URLs, temp storage and a bot double.

Everything random comes from the `faker` fixture; no assertion may depend on a particular
generated value.
"""

from collections.abc import Callable, Generator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from faker import Faker
from gallery_dl import config as gdl_config
from pytest_mock import MockerFixture

from config import Settings, settings
from database import init_db
from tests.constants import (
    GALLERY_DL_HOST,
    GALLERY_DL_POST_KIND,
    INSTAGRAM_HOSTS,
    INSTAGRAM_POST_KINDS,
    SCHEME_HTTPS,
    SCHEME_SEPARATOR,
    TIKTOK_HOSTS,
    UNSUPPORTED_TLD,
)


def _tiktok_link(faker: Faker) -> str:
    host = faker.random_element(TIKTOK_HOSTS)
    path = f"@{faker.pystr(min_chars=5, max_chars=12)}/video/{faker.pyint()}"
    return f"{SCHEME_HTTPS}{SCHEME_SEPARATOR}{host}/{path}"


def _instagram_link(faker: Faker) -> str:
    host = faker.random_element(INSTAGRAM_HOSTS)
    kind = faker.random_element(INSTAGRAM_POST_KINDS)
    return (
        f"{SCHEME_HTTPS}{SCHEME_SEPARATOR}{host}/{kind}/{faker.pystr(min_chars=8, max_chars=12)}"
    )


@pytest.fixture(scope="session")
def faker() -> Faker:
    """One shared, unseeded Faker (English and Russian locales) for all generated scalars."""
    return Faker(["en_US", "ru_RU"])


@pytest.fixture(autouse=True)
def _test_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, faker: Faker) -> None:
    """Reset the shared `config.settings` to its defaults for the test.

    DATABASE_PATH and DOWNLOAD_DIR point at not yet created names inside `tmp_path`, so no
    test can touch the real cache database or download directory.
    """
    for name, field_value in Settings().model_dump().items():
        monkeypatch.setattr(settings, name, field_value)
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / f"{faker.pystr()}.db"))
    monkeypatch.setattr(settings, "DOWNLOAD_DIR", str(tmp_path / faker.pystr()))


@pytest.fixture(autouse=True)
def _clean_gallery_dl_config() -> Generator[None]:
    """Clear gallery-dl's process-wide configuration after every test."""
    yield
    gdl_config.clear()


@pytest.fixture
async def database_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, faker: Faker) -> Path:
    """Point DATABASE_PATH at a fresh file in `tmp_path`, run `init_db()`; return the path."""
    database = tmp_path / f"{faker.pystr()}.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", str(database))
    await init_db()
    return database


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
def make_url(faker: Faker) -> Callable[[], str]:
    """Factory: every call returns a new clean supported link (TikTok or Instagram)."""

    def make() -> str:
        build = faker.random_element((_tiktok_link, _instagram_link))
        return str(build(faker))

    return make


@pytest.fixture
def gallery_dl_url(faker: Faker) -> str:
    """An Instagram post link that a real gallery-dl extractor accepts (for `Job(...)`)."""
    token = faker.pystr(min_chars=8, max_chars=12)
    return f"{SCHEME_HTTPS}{SCHEME_SEPARATOR}{GALLERY_DL_HOST}/{GALLERY_DL_POST_KIND}/{token}"


@pytest.fixture
def unsupported_url(faker: Faker) -> str:
    """A link no gallery-dl extractor and not the bot supports (reserved `.invalid` TLD)."""
    name = faker.pystr(min_chars=5, max_chars=12).lower()
    return f"{SCHEME_HTTPS}{SCHEME_SEPARATOR}{name}.{UNSUPPORTED_TLD}/{faker.pystr()}"


@pytest.fixture
def video_file_id(faker: Faker) -> str:
    """The Telegram file id that `bot.send_video` reports back."""
    return str(faker.pystr(min_chars=10, max_chars=30))


@pytest.fixture
def photo_file_id(faker: Faker) -> str:
    """The Telegram file id that `bot.send_photo` reports back (as the last photo size)."""
    return str(faker.pystr(min_chars=10, max_chars=30))


@pytest.fixture
def bot(mocker: MockerFixture, faker: Faker, video_file_id: str, photo_file_id: str) -> AsyncMock:
    """An AsyncMock bot with a random `id`.

    `send_video` returns an object whose `.video.file_id` is `video_file_id`; `send_photo`
    one whose `.photo[-1].file_id` is `photo_file_id`. Every other method is a plain AsyncMock.
    """
    stub: AsyncMock = mocker.AsyncMock(id=faker.pyint(min_value=1))
    stub.send_video.return_value = SimpleNamespace(video=SimpleNamespace(file_id=video_file_id))
    stub.send_photo.return_value = SimpleNamespace(photo=[SimpleNamespace(file_id=photo_file_id)])
    return stub
