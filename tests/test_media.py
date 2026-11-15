from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import Chat, Message

from src.handlers.media import _process_url


async def test_unbound_message_fails_explicitly() -> None:
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
    )
    with (
        patch("src.database.get_cached_media", new=AsyncMock(return_value=None)),
        pytest.raises(RuntimeError, match="Message is not bound to a bot"),
    ):
        await _process_url(message, "https://vm.tiktok.com/test")
