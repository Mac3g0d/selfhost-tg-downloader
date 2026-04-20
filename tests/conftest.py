from collections.abc import Iterator
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-for-ci")
    monkeypatch.setenv("COOKIES_FILE", "")
    monkeypatch.setenv("INSTAGRAM_USER", "")
    monkeypatch.setenv("INSTAGRAM_PASS", "")
    monkeypatch.setenv("BUFFER_CHAT_ID", "0")

    import config

    with patch.object(config, "settings", config.Settings()):
        yield
