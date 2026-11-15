from datetime import UTC, datetime

import pytest
from aiogram.types import Chat, Message, User
from pytest_mock import MockerFixture

from handlers.media import _process_url, on_message


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
