"""Isolate the environment before anything imports the application; register the fixtures.

``config.settings`` is built on first import, so the environment is prepared here, in the
conftest body, before pytest imports the fixture plugin modules below (they import the app).
"""

import atexit

from tests.environment import isolate

atexit.register(isolate().undo)

pytest_plugins = (
    "tests.fixtures.core",
    "tests.fixtures.builders",
    "tests.fixtures.detection",
    "tests.fixtures.inflight",
    "tests.fixtures.inline",
    "tests.fixtures.downloading",
    "tests.fixtures.chat",
)
