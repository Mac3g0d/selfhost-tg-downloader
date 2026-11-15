from pathlib import Path

import pytest

from downloader.gallery import MediaFile, _collect_media

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".avi")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    (tmp_path / "video.mp4").write_bytes(b"\x00" * 100)
    (tmp_path / "photo.jpg").write_bytes(b"\x00" * 50)
    (tmp_path / "readme.txt").write_text("ignore me")
    return tmp_path


def test_collect_media_finds_video_and_image(media_dir: Path) -> None:
    files = _collect_media(media_dir)
    assert len(files) == 2

    videos = [media for media in files if media.is_video]
    images = [media for media in files if not media.is_video]
    assert len(videos) == 1
    assert len(images) == 1
    assert videos[0].path.suffix == ".mp4"
    assert images[0].path.suffix == ".jpg"


def test_collect_media_empty_dir(tmp_path: Path) -> None:
    files = _collect_media(tmp_path)
    assert files == []


def test_media_file_frozen() -> None:
    mf = MediaFile(path=Path("/tmp/test.mp4"), is_video=True)
    with pytest.raises(AttributeError):
        mf.__setattr__("path", Path("/other"))


def test_collect_media_nested_dirs(tmp_path: Path) -> None:
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.mov").write_bytes(b"\x00" * 10)
    (tmp_path / "top.png").write_bytes(b"\x00" * 10)

    files = _collect_media(tmp_path)
    assert len(files) == 2
    suffixes = {media.path.suffix for media in files}
    assert suffixes == {".mov", ".png"}


def test_collect_media_all_extensions(tmp_path: Path) -> None:
    for ext in VIDEO_EXTS + IMAGE_EXTS:
        (tmp_path / f"file{ext}").write_bytes(b"\x00")

    files = _collect_media(tmp_path)
    videos = [media for media in files if media.is_video]
    images = [media for media in files if not media.is_video]
    assert len(videos) == len(VIDEO_EXTS)
    assert len(images) == len(IMAGE_EXTS)


def test_collect_media_ignores_unknown_extensions(tmp_path: Path) -> None:
    (tmp_path / "file.pdf").write_bytes(b"\x00")
    (tmp_path / "file.docx").write_bytes(b"\x00")
    (tmp_path / "file.html").write_bytes(b"\x00")

    assert _collect_media(tmp_path) == []


def test_collect_media_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "VIDEO.MP4").write_bytes(b"\x00")
    (tmp_path / "Photo.JPG").write_bytes(b"\x00")

    files = _collect_media(tmp_path)
    assert len(files) == 2
