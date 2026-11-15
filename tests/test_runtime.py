"""Smoke tests for the installed package and its console entry point."""

import importlib

import pytest


@pytest.mark.parametrize(
    "name",
    [
        "src.__main__",
        "src.bot",
        "src.database",
        "src.downloader.gallery",
        "src.handlers.inline",
        "src.handlers.media",
        "src.healthcheck",
    ],
)
def test_package_modules_import(name: str) -> None:
    assert importlib.import_module(name).__name__ == name


def test_console_entry_point_imports() -> None:
    from importlib.metadata import distribution

    entry = next(
        ep for ep in distribution("selfhost-tg-downloader").entry_points if ep.name == "bot"
    )
    assert callable(entry.load())
