import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import settings
from src.downloader.gallery import _build_cmd, _build_gallery_dl_config, cleanup


class TestBuildGalleryDlConfig:
    def test_returns_none_without_credentials(self, tmp_path: Path) -> None:
        assert _build_gallery_dl_config(tmp_path) is None

    def test_creates_config_with_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "INSTAGRAM_USER", "testuser")
        monkeypatch.setattr(settings, "INSTAGRAM_PASS", "testpass")

        config_path = _build_gallery_dl_config(tmp_path)

        assert config_path is not None
        assert config_path.exists()

        data = json.loads(config_path.read_text())
        assert data["extractor"]["instagram"]["username"] == "testuser"
        assert data["extractor"]["instagram"]["password"] == "testpass"

    def test_partial_credentials_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "INSTAGRAM_USER", "testuser")
        monkeypatch.setattr(settings, "INSTAGRAM_PASS", "")
        assert _build_gallery_dl_config(tmp_path) is None


class TestBuildCmd:
    def test_base_cmd(self, tmp_path: Path) -> None:
        cmd = _build_cmd(tmp_path)
        assert cmd[0] == "gallery-dl"
        assert "--no-mtime" in cmd
        assert "--dest" in cmd
        assert str(tmp_path) in cmd

    def test_with_cookies_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cookies = tmp_path / "cookies.txt"
        cookies.write_text("cookie data")
        monkeypatch.setattr(settings, "COOKIES_FILE", str(cookies))

        cmd = _build_cmd(tmp_path)

        assert "--cookies" in cmd
        assert str(cookies) in cmd

    def test_without_cookies_file(self, tmp_path: Path) -> None:
        cmd = _build_cmd(tmp_path)
        assert "--cookies" not in cmd

    def test_credentials_take_priority_over_cookies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cookies = tmp_path / "cookies.txt"
        cookies.write_text("cookie data")
        monkeypatch.setattr(settings, "COOKIES_FILE", str(cookies))
        monkeypatch.setattr(settings, "INSTAGRAM_USER", "user")
        monkeypatch.setattr(settings, "INSTAGRAM_PASS", "pass")

        cmd = _build_cmd(tmp_path)

        assert "--config" in cmd
        assert "--cookies" not in cmd


class TestCleanup:
    def test_requests_directory_cleanup(self, tmp_path: Path) -> None:
        with patch("src.downloader.gallery.shutil.rmtree") as remove_tree:
            cleanup(tmp_path)
        remove_tree.assert_called_once_with(tmp_path, ignore_errors=True)

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        with patch("src.downloader.gallery.shutil.rmtree") as remove_tree:
            cleanup(missing)
        remove_tree.assert_called_once_with(missing, ignore_errors=True)
