"""Fixtures for the media collection tests."""

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest
from faker import Faker

from constants import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from downloader.gallery import MediaFile
from tests.constants import (
    COLLECT_CONTENT_LENGTH,
    COLLECT_NAME_MAX_CHARS,
    COLLECT_NAME_MIN_CHARS,
    FOREIGN_EXTENSIONS,
)
from tests.factories import MediaFileFactory

type FileMaker = Callable[[Path, str], Path]


class Library(NamedTuple):
    """A directory together with the (path, is_video) pairs expected to be collected from it."""

    directory: Path
    expected: set[tuple[Path, bool]]


@pytest.fixture(params=sorted(VIDEO_EXTENSIONS))
def video_extension(request: pytest.FixtureRequest) -> str:
    """Every supported video extension, one test run per extension."""
    return str(request.param)


@pytest.fixture(params=sorted(IMAGE_EXTENSIONS))
def image_extension(request: pytest.FixtureRequest) -> str:
    """Every supported image extension, one test run per extension."""
    return str(request.param)


@pytest.fixture(params=sorted(VIDEO_EXTENSIONS | IMAGE_EXTENSIONS))
def supported_extension(request: pytest.FixtureRequest) -> str:
    """Every supported extension, video or image, one test run per extension."""
    return str(request.param)


@pytest.fixture(params=sorted(FOREIGN_EXTENSIONS))
def foreign_extension(request: pytest.FixtureRequest) -> str:
    """Every extension the collector must ignore, one test run per extension."""
    return str(request.param)


@pytest.fixture
def library_dir(tmp_path: Path, faker: Faker) -> Path:
    """A new empty directory with a generated name."""
    directory = tmp_path / faker.pystr(
        min_chars=COLLECT_NAME_MIN_CHARS, max_chars=COLLECT_NAME_MAX_CHARS
    )
    directory.mkdir()
    return directory


@pytest.fixture
def make_file(faker: Faker) -> FileMaker:
    """Create a file with a generated name and content, given a directory and an extension."""

    def factory(directory: Path, extension: str) -> Path:
        name = faker.pystr(min_chars=COLLECT_NAME_MIN_CHARS, max_chars=COLLECT_NAME_MAX_CHARS)
        path = directory / f"{name}{extension}"
        path.write_bytes(faker.binary(length=COLLECT_CONTENT_LENGTH))
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
    make_file(library_dir, min(FOREIGN_EXTENSIONS))
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
        directory=library_dir, expected={(path, supported_extension in VIDEO_EXTENSIONS)}
    )


@pytest.fixture
def full_library(library_dir: Path, make_file: FileMaker) -> Library:
    """One file per supported extension."""
    videos = {(make_file(library_dir, extension), True) for extension in VIDEO_EXTENSIONS}
    images = {(make_file(library_dir, extension), False) for extension in IMAGE_EXTENSIONS}
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
def media_file() -> MediaFile:
    """A generated media file."""
    return MediaFileFactory.build()


@pytest.fixture
def other_path(faker: Faker) -> Path:
    """A path different from the one of `media_file`."""
    return Path(faker.pystr(min_chars=COLLECT_NAME_MIN_CHARS, max_chars=COLLECT_NAME_MAX_CHARS))
