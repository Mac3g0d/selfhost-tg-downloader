from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import Chat, Message, User
from pytest_mock import MockerFixture

from downloader.gallery import DownloadResult
from handlers import delivery
from handlers.media import _process_url, on_message
from timing import StageTimer


async def test_unbound_message_fails_explicitly(mocker: MockerFixture) -> None:
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
    )
    mocker.patch("database.get_cached_media", new=mocker.AsyncMock(return_value=None))
    with pytest.raises(RuntimeError, match="Message is not bound to a bot"):
        await _process_url(message, "https://vm.tiktok.com/test")


async def test_own_inline_placeholder_is_not_answered(mocker: MockerFixture) -> None:
    bot = mocker.Mock(id=777)
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        text="⏳ Скачиваю…\n🔗 https://vm.tiktok.com/test",
        via_bot=User(id=777, is_bot=True, first_name="bot"),
    ).as_(bot)
    process = mocker.patch("handlers.media._process_url")

    await on_message(message)

    process.assert_not_called()


async def test_link_sent_through_another_bot_is_processed(mocker: MockerFixture) -> None:
    bot = mocker.Mock(id=777)
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        text="https://vm.tiktok.com/test",
        via_bot=User(id=555, is_bot=True, first_name="other"),
    ).as_(bot)
    process = mocker.patch("handlers.media._process_url", new=mocker.AsyncMock())

    await on_message(message)

    process.assert_awaited_once()


LONG_ERROR = "<html> & ".ljust(5000, "x")


def _bound_message(mocker: MockerFixture) -> tuple[Message, Any, Any]:
    bot = mocker.AsyncMock(id=777)
    status = mocker.AsyncMock()
    bot.return_value = status
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        text="https://vm.tiktok.com/test",
    ).as_(bot)
    return message, bot, status


async def test_download_error_is_escaped_and_shortened(mocker: MockerFixture) -> None:
    message, _, status = _bound_message(mocker)
    mocker.patch("database.get_cached_media", new=mocker.AsyncMock(return_value=None))
    failed = DownloadResult(success=False, error=LONG_ERROR)
    mocker.patch.object(delivery, "download_media", new=mocker.AsyncMock(return_value=failed))

    await delivery.deliver_url(message, "https://vm.tiktok.com/test", StageTimer())

    text = status.edit_text.call_args.args[0]
    assert "&lt;html&gt; &amp; " in text
    assert len(text) < 400


async def test_failed_activity_hint_does_not_cancel_delivery(mocker: MockerFixture) -> None:
    message, bot, status = _bound_message(mocker)
    bot.send_chat_action.side_effect = TelegramNetworkError(
        method=mocker.Mock(), message="timeout"
    )

    announced = await delivery._announce(message, bot)

    assert announced is status
