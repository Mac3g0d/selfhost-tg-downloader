"""Smoke tests for the installed package and its console entry point."""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "name",
    [
        "tg_downloader",
        "bot",
        "database",
        "downloader.gallery",
        "handlers.inline",
        "handlers.media",
        "healthcheck",
    ],
)
def test_package_modules_import(name: str) -> None:
    assert importlib.import_module(name).__name__ == name


def test_console_entry_point_imports() -> None:
    from importlib.metadata import distribution

    entry = next(
        ep for ep in distribution("selfhost-tg-downloader").entry_points if ep.name == "bot"
    )
    assert entry.value == "tg_downloader:main"
    assert callable(entry.load())


def test_installed_entry_point_outside_checkout(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "from importlib.metadata import distribution; "
            "entry = next(ep for ep in distribution('selfhost-tg-downloader').entry_points "
            "if ep.name == 'bot'); "
            "assert entry.value == 'tg_downloader:main'; assert callable(entry.load()); "
            "import bot, downloader.gallery, handlers.media; print('installed entry point OK')",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == "installed entry point OK"
