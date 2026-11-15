from pathlib import Path
from unittest.mock import AsyncMock, call

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage
from aiogram.types import Message
from pytest_mock import MockerFixture

import database
from constants import ERROR_TEXT_LIMIT
from handlers import delivery
from handlers.media import _process_url, on_message
from tests.constants import FAILURE_MARK, FAILURE_MARKUP_ALLOWANCE, UNBOUND_MESSAGE_PATTERN
from tests.fixtures.chat import CachedLink, DeliveryCase, FailedDownload, LinkPair, Telegram
from timing import StageTimer


async def test_unbound_message_fails_explicitly(
    unbound_message: Message, supported_url: str, database_ready: Path
) -> None:
    with pytest.raises(RuntimeError, match=UNBOUND_MESSAGE_PATTERN):
        await _process_url(unbound_message, supported_url)


async def test_own_inline_placeholder_is_not_answered(
    own_placeholder_message: Message, process_url: AsyncMock
) -> None:
    await on_message(own_placeholder_message)

    process_url.assert_not_called()


async def test_link_sent_through_another_bot_is_processed(
    foreign_via_message: Message, supported_url: str, process_url: AsyncMock
) -> None:
    await on_message(foreign_via_message)

    process_url.assert_awaited_once_with(foreign_via_message, supported_url)


async def test_message_without_text_is_ignored(
    textless_message: Message, process_url: AsyncMock
) -> None:
    await on_message(textless_message)

    process_url.assert_not_called()


async def test_two_links_are_processed_in_order(
    two_link_message: LinkPair, process_url: AsyncMock
) -> None:
    await on_message(two_link_message.message)

    assert process_url.await_args_list == [
        call(two_link_message.message, url) for url in two_link_message.urls
    ]


async def test_download_error_is_escaped_and_shortened(
    link_message: Message,
    supported_url: str,
    timer: StageTimer,
    telegram: Telegram,
    failed_download: FailedDownload,
) -> None:
    await delivery.deliver_url(link_message, supported_url, timer)

    text = telegram.edited_text()
    assert FAILURE_MARK in text
    assert failed_download.escaped_start in text
    assert len(text) < ERROR_TEXT_LIMIT + FAILURE_MARKUP_ALLOWANCE


async def test_failed_activity_hint_does_not_cancel_delivery(
    link_message: Message, bot: AsyncMock, telegram: Telegram, mocker: MockerFixture
) -> None:
    bot.send_chat_action.side_effect = TelegramNetworkError(
        method=mocker.Mock(), message="timeout"
    )

    announced = await delivery._announce(link_message, bot)

    assert announced is telegram.status


async def test_cached_link_is_answered_with_cached_file_ids(
    link_message: Message,
    supported_url: str,
    timer: StageTimer,
    telegram: Telegram,
    cached_link: CachedLink,
) -> None:
    await delivery.deliver_url(link_message, supported_url, timer)

    assert telegram.sent_files() == cached_link.expected_files


async def test_cached_link_is_not_downloaded(
    link_message: Message,
    supported_url: str,
    timer: StageTimer,
    telegram: Telegram,
    cached_link: CachedLink,
) -> None:
    await delivery.deliver_url(link_message, supported_url, timer)

    cached_link.download.assert_not_awaited()
    assert SendMessage not in telegram.kinds()


async def test_downloaded_file_is_sent_after_the_status_message(
    link_message: Message,
    supported_url: str,
    timer: StageTimer,
    telegram: Telegram,
    delivery_case: DeliveryCase,
) -> None:
    await delivery.deliver_url(link_message, supported_url, timer)

    assert telegram.kinds() == [SendMessage, delivery_case.method_type]


async def test_downloaded_file_is_cached(
    link_message: Message,
    supported_url: str,
    timer: StageTimer,
    telegram: Telegram,
    delivery_case: DeliveryCase,
) -> None:
    await delivery.deliver_url(link_message, supported_url, timer)

    assert await database.get_cached_media(supported_url) == [delivery_case.cache_item]


async def test_status_message_is_deleted_after_sending(
    link_message: Message,
    supported_url: str,
    timer: StageTimer,
    telegram: Telegram,
    delivery_case: DeliveryCase,
) -> None:
    await delivery.deliver_url(link_message, supported_url, timer)

    telegram.status.delete.assert_awaited_once_with()


async def test_work_directory_is_removed_after_sending(
    link_message: Message,
    supported_url: str,
    timer: StageTimer,
    telegram: Telegram,
    delivery_case: DeliveryCase,
) -> None:
    await delivery.deliver_url(link_message, supported_url, timer)

    assert not delivery_case.work_dir.exists()
