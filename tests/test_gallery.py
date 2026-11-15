import json
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from config import settings
from downloader.gallery import _build_cmd, _build_gallery_dl_config, cleanup


def test_returns_none_without_credentials(tmp_path: Path) -> None:
    assert _build_gallery_dl_config(tmp_path) is None


def test_creates_config_with_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INSTAGRAM_USER", "testuser")
    monkeypatch.setattr(settings, "INSTAGRAM_PASS", "testpass")

    config_path = _build_gallery_dl_config(tmp_path)

    assert config_path is not None
    assert config_path.exists()

    data = json.loads(config_path.read_text())
    assert data["extractor"]["instagram"]["username"] == "testuser"
    assert data["extractor"]["instagram"]["password"] == "testpass"


def test_partial_credentials_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INSTAGRAM_USER", "testuser")
    monkeypatch.setattr(settings, "INSTAGRAM_PASS", "")
    assert _build_gallery_dl_config(tmp_path) is None


def test_base_cmd(tmp_path: Path) -> None:
    cmd = _build_cmd(tmp_path)
    assert cmd[0] == "gallery-dl"
    assert "--no-mtime" in cmd
    assert "--dest" in cmd
    assert str(tmp_path) in cmd


def test_with_cookies_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("cookie data")
    monkeypatch.setattr(settings, "COOKIES_FILE", str(cookies))

    cmd = _build_cmd(tmp_path)

    assert "--cookies" in cmd
    assert str(cookies) in cmd


def test_without_cookies_file(tmp_path: Path) -> None:
    cmd = _build_cmd(tmp_path)
    assert "--cookies" not in cmd


def test_credentials_take_priority_over_cookies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("cookie data")
    monkeypatch.setattr(settings, "COOKIES_FILE", str(cookies))
    monkeypatch.setattr(settings, "INSTAGRAM_USER", "user")
    monkeypatch.setattr(settings, "INSTAGRAM_PASS", "pass")

    cmd = _build_cmd(tmp_path)

    assert "--config" in cmd
    assert "--cookies" not in cmd


def test_requests_directory_cleanup(tmp_path: Path, mocker: MockerFixture) -> None:
    remove_tree = mocker.patch("downloader.gallery.shutil.rmtree")
    cleanup(tmp_path)
    remove_tree.assert_called_once_with(tmp_path, ignore_errors=True)


def test_nonexistent_directory(tmp_path: Path, mocker: MockerFixture) -> None:
    missing = tmp_path / "nonexistent"
    remove_tree = mocker.patch("downloader.gallery.shutil.rmtree")
    cleanup(missing)
    remove_tree.assert_called_once_with(missing, ignore_errors=True)
