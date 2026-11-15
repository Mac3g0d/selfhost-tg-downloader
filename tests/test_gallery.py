import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from gallery_dl import config as gdl_config
from pytest_mock import MockerFixture

from config import settings
from downloader.gallery import _apply_settings, _Job, _run_job, cleanup, download_media

INSTAGRAM = ("extractor", "instagram")
POST_URL = "https://www.instagram.com/p/ABCDEFGHIJK"
RUN_JOB = "downloader.gallery._run_job"
CLEANUP_WAIT_SECONDS = 1


def _wait_until_empty(directory: Path) -> None:
    deadline = time.monotonic() + CLEANUP_WAIT_SECONDS
    while any(directory.iterdir()) and time.monotonic() < deadline:
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def _clean_gallery_dl_config() -> Any:
    yield
    gdl_config.clear()


def test_settings_without_auth() -> None:
    _apply_settings()

    assert gdl_config.get((), "cookies") is None
    assert gdl_config.get(INSTAGRAM, "username") is None
    assert gdl_config.get((), "mtime") is False
    assert gdl_config.get(("output",), "mode") == "null"


def test_settings_with_cookies_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("cookie data")
    monkeypatch.setattr(settings, "COOKIES_FILE", str(cookies))

    _apply_settings()

    assert gdl_config.get((), "cookies") == str(cookies)


def test_missing_cookies_file_is_not_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "COOKIES_FILE", str(tmp_path / "absent.txt"))

    _apply_settings()

    assert gdl_config.get((), "cookies") is None


def test_credentials_take_priority_over_cookies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("cookie data")
    monkeypatch.setattr(settings, "COOKIES_FILE", str(cookies))
    monkeypatch.setattr(settings, "INSTAGRAM_USER", "user")
    monkeypatch.setattr(settings, "INSTAGRAM_PASS", "pass")

    _apply_settings()

    assert gdl_config.get(INSTAGRAM, "username") == "user"
    assert gdl_config.get(INSTAGRAM, "password") == "pass"
    assert gdl_config.get((), "cookies") is None


def test_partial_credentials_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INSTAGRAM_USER", "user")
    monkeypatch.setattr(settings, "INSTAGRAM_PASS", "")

    _apply_settings()

    assert gdl_config.get(INSTAGRAM, "username") is None


def test_credentials_are_removed_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INSTAGRAM_USER", "user")
    monkeypatch.setattr(settings, "INSTAGRAM_PASS", "pass")
    _apply_settings()
    monkeypatch.setattr(settings, "INSTAGRAM_USER", "")

    _apply_settings()

    assert gdl_config.get(INSTAGRAM, "password") is None


def test_each_job_answers_its_own_destination(tmp_path: Path) -> None:
    first = _Job(POST_URL, dest=tmp_path / "a")
    second = _Job(POST_URL, dest=tmp_path / "b")

    assert first.extractor.config("base-directory") == str(tmp_path / "a")
    assert second.extractor.config("base-directory") == str(tmp_path / "b")
    assert gdl_config.get((), "base-directory") is None


def test_child_job_inherits_destination_and_cancel_flag(tmp_path: Path) -> None:
    cancel = threading.Event()
    parent = _Job(POST_URL, dest=tmp_path, cancel=cancel)

    child = _Job(POST_URL, parent)

    assert child.extractor.config("base-directory") == str(tmp_path)
    assert child.cancel is cancel
    assert child.root is parent


async def test_successful_download_returns_files_and_timings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    monkeypatch.setattr(settings, "DOWNLOAD_DIR", str(tmp_path))

    def fake_job(url: str, work_dir: Path, cancel: threading.Event) -> tuple[int, str, None]:
        (work_dir / "clip.mp4").write_bytes(b"video")
        return 0, "", None

    mocker.patch(RUN_JOB, side_effect=fake_job)

    outcome = await download_media(POST_URL)

    assert outcome.success
    assert [media.path.name for media in outcome.media_files] == ["clip.mp4"]
    assert outcome.timings["download_ms"] >= 0
    assert outcome.work_dir is not None
    cleanup(outcome.work_dir)


async def test_failed_download_reports_gallery_dl_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    monkeypatch.setattr(settings, "DOWNLOAD_DIR", str(tmp_path))
    mocker.patch(RUN_JOB, return_value=(4, "[instagram][error] boom", None))

    outcome = await download_media(POST_URL)

    assert not outcome.success
    assert outcome.error == "[instagram][error] boom"
    assert list(tmp_path.iterdir()) == []


async def test_partial_download_is_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    monkeypatch.setattr(settings, "DOWNLOAD_DIR", str(tmp_path))

    def partial_job(url: str, work_dir: Path, cancel: threading.Event) -> tuple[int, str, None]:
        (work_dir / "first.jpg").write_bytes(b"photo")
        return 4, "[download][error] Failed to download second.jpg", None

    mocker.patch(RUN_JOB, side_effect=partial_job)

    outcome = await download_media(POST_URL)

    assert not outcome.success
    assert "second.jpg" in outcome.error
    assert list(tmp_path.iterdir()) == []


async def test_timeout_cancels_job_and_cleans_up_after_it_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    monkeypatch.setattr(settings, "DOWNLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "DOWNLOAD_TIMEOUT", 0.05)
    stopped = threading.Event()

    def slow_job(url: str, work_dir: Path, cancel: threading.Event) -> tuple[int, str, None]:
        assert cancel.wait(timeout=5)
        (work_dir / "late.mp4").write_bytes(b"late")
        stopped.set()
        return 1, "", None

    mocker.patch(RUN_JOB, side_effect=slow_job)

    outcome = await download_media(POST_URL)

    assert not outcome.success
    assert "timed out" in outcome.error
    assert stopped.wait(timeout=5)
    await asyncio.to_thread(_wait_until_empty, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_unsupported_url_is_reported(tmp_path: Path) -> None:
    status, error, first_file_at = _run_job(
        "https://example.com/nothing", tmp_path, threading.Event()
    )

    assert status != 0
    assert error == "Unsupported URL"
    assert first_file_at is None


def test_requests_directory_cleanup(tmp_path: Path, mocker: MockerFixture) -> None:
    remove_tree = mocker.patch("downloader.gallery.shutil.rmtree")
    cleanup(tmp_path)
    remove_tree.assert_called_once_with(tmp_path, ignore_errors=True)


def test_nonexistent_directory(tmp_path: Path, mocker: MockerFixture) -> None:
    missing = tmp_path / "nonexistent"
    remove_tree = mocker.patch("downloader.gallery.shutil.rmtree")
    cleanup(missing)
    remove_tree.assert_called_once_with(missing, ignore_errors=True)
