"""Smoke tests for the installed package and its console entry point."""

import importlib
from importlib.metadata import EntryPoint, distribution
from types import ModuleType

import pytest

from tests.constants import (
    DISTRIBUTION_NAME,
    ENTRY_POINT_NAME,
    ENTRY_POINT_TARGET,
    PACKAGE_MODULES,
)


@pytest.fixture
def entry_point() -> EntryPoint:
    """The console entry point of the installed distribution."""
    return next(
        point
        for point in distribution(DISTRIBUTION_NAME).entry_points
        if point.name == ENTRY_POINT_NAME
    )


@pytest.fixture
def entry_module(entry_point: EntryPoint) -> ModuleType:
    """The module the entry point lives in, imported."""
    return importlib.import_module(entry_point.module)


@pytest.mark.parametrize("module_name", PACKAGE_MODULES)
async def test_package_modules_import(module_name: str) -> None:
    imported = importlib.import_module(module_name)

    assert imported.__name__ == module_name


async def test_console_entry_point_targets_main(entry_point: EntryPoint) -> None:
    target = entry_point.value

    assert target == ENTRY_POINT_TARGET


async def test_console_entry_point_loads_the_callable(
    entry_point: EntryPoint, entry_module: ModuleType
) -> None:
    loaded = entry_point.load()

    assert callable(loaded)
    assert loaded is getattr(entry_module, entry_point.attr)
