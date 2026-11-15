from pathlib import Path

import pytest

from downloader.gallery import MediaFile, _collect_media
from tests.fixtures import Library


async def test_collect_media_finds_video_and_image(mixed_library: Library) -> None:
    files = _collect_media(mixed_library.directory)

    assert {(media.path, media.is_video) for media in files} == mixed_library.expected
    assert len(files) == len(mixed_library.expected)


async def test_collect_media_empty_dir(empty_library: Library) -> None:
    files = _collect_media(empty_library.directory)

    assert files == []


async def test_media_file_frozen(media_file: MediaFile, other_path: Path) -> None:
    original = media_file.path

    with pytest.raises(AttributeError):
        media_file.__setattr__("path", other_path)

    assert media_file.path == original


async def test_collect_media_nested_dirs(nested_library: Library) -> None:
    files = _collect_media(nested_library.directory)

    assert {(media.path, media.is_video) for media in files} == nested_library.expected
    assert len(files) == len(nested_library.expected)


async def test_collect_media_recognises_each_extension(single_library: Library) -> None:
    files = _collect_media(single_library.directory)

    assert {(media.path, media.is_video) for media in files} == single_library.expected
    assert len(files) == len(single_library.expected)


async def test_collect_media_all_extensions(full_library: Library) -> None:
    files = _collect_media(full_library.directory)

    assert {(media.path, media.is_video) for media in files} == full_library.expected
    assert len(files) == len(full_library.expected)


async def test_collect_media_ignores_unknown_extensions(foreign_library: Library) -> None:
    files = _collect_media(foreign_library.directory)

    assert files == []


async def test_collect_media_case_insensitive(shouting_library: Library) -> None:
    files = _collect_media(shouting_library.directory)

    assert {(media.path, media.is_video) for media in files} == shouting_library.expected
    assert len(files) == len(shouting_library.expected)
