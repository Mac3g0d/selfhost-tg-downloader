"""Isolate the environment before anything imports the application; register the fixtures.

``config.settings`` is built on first import, so the environment is prepared here, in the
conftest body, before pytest imports the fixture plugin module below (it imports the app).
"""

import atexit

import pytest
from faker import Faker

from tests.constants import EMPTY_TEXT


def isolate() -> pytest.MonkeyPatch:
    """Point every variable the settings read at a harmless value; return the undo handle."""
    faker = Faker()
    env = pytest.MonkeyPatch()
    secret = faker.pystr(min_chars=35, max_chars=35)
    env.setenv("TELEGRAM_BOT_TOKEN", f"{faker.pyint()}:{secret}")
    env.setenv("COOKIES_FILE", EMPTY_TEXT)
    env.setenv("INSTAGRAM_USER", EMPTY_TEXT)
    env.setenv("INSTAGRAM_PASS", EMPTY_TEXT)
    env.setenv("BUFFER_CHAT_ID", str(0))
    return env


atexit.register(isolate().undo)

pytest_plugins = ("tests.fixtures",)
