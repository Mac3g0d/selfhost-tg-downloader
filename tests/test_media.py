from datetime import UTC, datetime

import pytest
from aiogram.types import Chat, Message
from pytest_mock import MockerFixture

from handlers.media import _process_url


async def test_unbound_message_fails_explicitly(mocker: MockerFixture) -> None:
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
    )
    mocker.patch("database.get_cached_media", new=mocker.AsyncMock(return_value=None))
    with pytest.raises(RuntimeError, match="Message is not bound to a bot"):
        await _process_url(message, "https://vm.tiktok.com/test")
