import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock

from aiogram.types import (
    CallbackQuery,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedVideo,
    InputMediaPhoto,
    InputMediaVideo,
)

import constants as app
from database import get_cached_media, get_inline_link
from handlers import inline
from tests import constants as spec
from tests.fixtures.inline import Delivery, DownloadGate, Edits, FailingDownload, Requests


async def test_cache_miss_is_answered_at_once_with_placeholder(
    query: InlineQuery,
    bot: AsyncMock,
    slow_download: DownloadGate,
    requests: Requests,
    key: str,
) -> None:
    await inline.on_inline_query(query, bot)

    answer = requests.answer
    assert answer.cache_time == spec.UNCACHED_SECONDS
    assert answer.is_personal is True
    assert len(answer.results) == 1
    article = answer.results[0]
    assert isinstance(article, InlineQueryResultArticle)
    assert article.id == app.PLACEHOLDER_PREFIX + key
    assert article.reply_markup is not None
    assert requests.first_row(article.reply_markup)[0].callback_data == app.REFRESH_PREFIX + key


async def test_cache_miss_saves_the_link_while_the_download_runs(
    query: InlineQuery, bot: AsyncMock, slow_download: DownloadGate, key: str, supported_url: str
) -> None:
    await inline.on_inline_query(query, bot)

    assert await get_inline_link(key) == supported_url
    await asyncio.wait_for(slow_download.started.wait(), timeout=spec.PEER_TIMEOUT_SECONDS)
    assert not slow_download.release.is_set()


async def test_cache_hit_returns_media_directly(
    query: InlineQuery,
    bot: AsyncMock,
    cached_video: list[dict[str, str]],
    video_download: AsyncMock,
    requests: Requests,
) -> None:
    await inline.on_inline_query(query, bot)

    answer = requests.answer
    assert answer.cache_time == app.HIT_CACHE_SECONDS
    assert len(answer.results) == 1
    cached = answer.results[0]
    assert isinstance(cached, InlineQueryResultCachedVideo)
    assert cached.video_file_id == cached_video[0][app.KEY_FILE_ID]
    video_download.assert_not_called()


async def test_sent_placeholder_is_replaced_with_video(
    video_delivery: Delivery, bot: AsyncMock, edits: Edits, video_file_id: str
) -> None:
    await inline.on_placeholder_sent(video_delivery.chosen, bot)

    media = edits.edited_media
    assert isinstance(media, InputMediaVideo)
    assert media.media == video_file_id
    assert edits.edited_kwargs == {
        "inline_message_id": video_delivery.inline_message_id,
        "reply_markup": None,
    }
    bot.edit_message_reply_markup.assert_awaited_once_with(
        inline_message_id=video_delivery.inline_message_id
    )
    assert await get_cached_media(video_delivery.url) == [
        {app.KEY_TYPE: app.TYPE_VIDEO, app.KEY_FILE_ID: video_file_id}
    ]
    assert not video_delivery.work_dir.exists()


async def test_carousel_placeholder_becomes_first_file_and_caches_all(
    carousel_delivery: Delivery, bot: AsyncMock, edits: Edits, photo_file_id: str
) -> None:
    await inline.on_placeholder_sent(carousel_delivery.chosen, bot)

    media = edits.edited_media
    assert isinstance(media, InputMediaPhoto)
    assert media.media == photo_file_id
    assert media.caption is None
    row = edits.edited_row
    assert [button.text for button in row] == [
        spec.PREVIOUS_LABEL,
        spec.PAGE_COUNTER_TEMPLATE.format(page=1, total=2),
        spec.NEXT_LABEL,
    ]
    assert (
        row[2].callback_data == f"{app.PAGE_PREFIX}{carousel_delivery.key}{spec.PAGE_SEPARATOR}1"
    )
    bot.edit_message_reply_markup.assert_not_called()
    entry = {app.KEY_TYPE: app.TYPE_PHOTO, app.KEY_FILE_ID: photo_file_id}
    assert await get_cached_media(carousel_delivery.url) == [entry, entry]


async def test_query_and_delivery_share_one_download(
    shared_delivery: Delivery, bot: AsyncMock, video_download: AsyncMock
) -> None:
    await inline.on_placeholder_sent(shared_delivery.chosen, bot)

    assert video_download.call_count == 1
    assert bot.send_video.await_count == 1


async def test_failed_download_is_shown_with_retry_button(
    failing_delivery: Delivery,
    bot: AsyncMock,
    failing_download: FailingDownload,
    edits: Edits,
) -> None:
    await inline.on_placeholder_sent(failing_delivery.chosen, bot)

    bot.edit_message_media.assert_not_called()
    assert spec.FAILURE_MARK in edits.status_text
    assert failing_download.escaped in edits.status_text
    assert failing_download.reason not in edits.status_text
    assert edits.status_button.text == app.TEXT_RETRY
    assert edits.status_button.callback_data == app.REFRESH_PREFIX + failing_delivery.key


async def test_refresh_button_delivers_from_cache(
    refresh_callback: CallbackQuery,
    bot: AsyncMock,
    cached_photo: list[dict[str, str]],
    edits: Edits,
) -> None:
    await inline.on_refresh(refresh_callback, bot)

    media = edits.edited_media
    assert isinstance(media, InputMediaPhoto)
    assert media.media == cached_photo[0][app.KEY_FILE_ID]


async def test_refresh_with_unknown_link_asks_to_resend(
    unknown_refresh_callback: CallbackQuery, bot: AsyncMock, requests: Requests
) -> None:
    await inline.on_refresh(unknown_refresh_callback, bot)

    assert requests.callback_answer.show_alert is True
    bot.edit_message_media.assert_not_called()


async def test_keyboard_already_removed_is_not_an_error(
    interrupted_delivery: Delivery, bot: AsyncMock, edits: Edits
) -> None:
    await inline.on_placeholder_sent(interrupted_delivery.chosen, bot)

    bot.edit_message_media.assert_awaited_once()
    assert all(spec.FAILURE_MARK not in text for text in edits.status_texts)


async def test_pager_flips_to_requested_file_and_wraps(
    make_page_callback: Callable[[int], CallbackQuery],
    bot: AsyncMock,
    cached_mixed_carousel: list[dict[str, str]],
    edits: Edits,
    key: str,
) -> None:
    await inline.on_page(make_page_callback(1), bot)

    media = edits.edited_media
    assert isinstance(media, InputMediaVideo)
    assert media.media == cached_mixed_carousel[1][app.KEY_FILE_ID]
    row = edits.edited_row
    assert row[1].text == spec.PAGE_COUNTER_TEMPLATE.format(page=2, total=2)
    assert row[1].callback_data == app.PAGE_NOOP
    assert row[2].callback_data == f"{app.PAGE_PREFIX}{key}{spec.PAGE_SEPARATOR}0"


async def test_cached_carousel_results_carry_the_pager(
    query: InlineQuery,
    bot: AsyncMock,
    cached_photo_carousel: list[dict[str, str]],
    requests: Requests,
) -> None:
    await inline.on_inline_query(query, bot)

    second = requests.answer.results[1]
    assert second.reply_markup is not None
    assert requests.first_row(second.reply_markup)[1].text == spec.PAGE_COUNTER_TEMPLATE.format(
        page=2, total=2
    )


async def test_pager_for_forgotten_post_asks_to_resend(
    forgotten_page_callback: CallbackQuery, bot: AsyncMock, requests: Requests
) -> None:
    await inline.on_page(forgotten_page_callback, bot)

    assert requests.callback_answer.show_alert is True
    bot.edit_message_media.assert_not_called()


async def test_pager_works_for_post_cached_outside_inline(
    carousel_next_payload: str,
    make_callback: Callable[..., CallbackQuery],
    bot: AsyncMock,
    cached_photo_carousel: list[dict[str, str]],
    edits: Edits,
) -> None:
    await inline.on_page(make_callback(carousel_next_payload), bot)

    assert edits.edited_media.media == cached_photo_carousel[1][app.KEY_FILE_ID]


async def test_page_counter_press_is_answered_silently(
    make_callback: Callable[..., CallbackQuery], bot: AsyncMock, requests: Requests
) -> None:
    await inline.on_page_counter(make_callback(app.PAGE_NOOP))

    assert not requests.callback_answer.show_alert
    bot.edit_message_media.assert_not_called()


async def test_failed_status_edit_does_not_cancel_delivery(
    flooded_delivery: Delivery, bot: AsyncMock, edits: Edits, video_file_id: str
) -> None:
    await inline.on_placeholder_sent(flooded_delivery.chosen, bot)

    bot.edit_message_text.assert_awaited()
    assert edits.edited_media.media == video_file_id


async def test_telegram_outage_on_replace_offers_retry(
    outage_delivery: Delivery, bot: AsyncMock, edits: Edits, video_file_id: str
) -> None:
    await inline.on_placeholder_sent(outage_delivery.chosen, bot)

    assert edits.status_button.text == app.TEXT_RETRY
    assert await get_cached_media(outage_delivery.url) == [
        {app.KEY_TYPE: app.TYPE_VIDEO, app.KEY_FILE_ID: video_file_id}
    ]


async def test_too_many_preparations_are_refused(
    other_query: InlineQuery, bot: AsyncMock, slow_download: DownloadGate, requests: Requests
) -> None:
    await inline.on_inline_query(other_query, bot)

    answer = requests.answer
    assert answer.results == []
    assert answer.button is not None
    assert answer.cache_time == app.SHORT_CACHE_SECONDS
    assert len(inline._jobs) == 1
    assert slow_download.download.call_count == 1
