import pytest


def pytest_configure(config: pytest.Config) -> None:
    # Settings are constructed during collection, before fixtures run.
    env = pytest.MonkeyPatch()
    env.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    env.setenv("COOKIES_FILE", "")
    env.setenv("INSTAGRAM_USER", "")
    env.setenv("INSTAGRAM_PASS", "")
    env.setenv("BUFFER_CHAT_ID", "0")
    config.add_cleanup(env.undo)


@pytest.fixture(autouse=True)
def _test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import Settings, settings

    # Mutate the shared object, not the config module's binding: callers import it.
    for name, field_value in Settings().model_dump().items():
        monkeypatch.setattr(settings, name, field_value)
