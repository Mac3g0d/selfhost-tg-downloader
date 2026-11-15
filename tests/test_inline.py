import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import exceptions, methods
from aiogram import types as tg_types
from pytest_mock import MockerFixture

from config import settings
from constants import PAGE_PREFIX, PLACEHOLDER_PREFIX, REFRESH_PREFIX, TEXT_RETRY
from database import (
    get_cached_media,
    get_inline_link,
    init_db,
    save_inline_link,
    set_cached_media,
)
from downloader.gallery import DownloadResult, MediaFile
from handlers import inline
from handlers import inline_ui as ui

URL = "https://www.instagram.com/reel/ABCDEFGHIJK"
USER = tg_types.User(id=42, is_bot=False, first_name="Tester")


@pytest.fixture(autouse=True)
async def _inline_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "cache.db"))
    monkeypatch.setattr(settings, "BUFFER_CHAT_ID", -100123)
    await init_db()
    yield
    for job in list(inline._jobs.values()):
        if job.task:
            job.task.cancel()
    inline._jobs.clear()
    inline._delivering.clear()


@pytest.fixture
def bot(mocker: MockerFixture) -> Any:
    fake = mocker.AsyncMock()
    fake.send_video.return_value = SimpleNamespace(video=SimpleNamespace(file_id="video-id"))
    fake.send_photo.return_value = SimpleNamespace(photo=[SimpleNamespace(file_id="photo-id")])
    return fake


def _download(tmp_path: Path, mocker: MockerFixture, names: list[str]) -> Any:
    def make(url: str) -> DownloadResult:
        work_dir = tmp_path / "work"
        work_dir.mkdir(exist_ok=True)
        files = []
        for name in names:
            path = work_dir / name
            path.write_bytes(b"media")
            files.append(MediaFile(path=path, is_video=name.endswith(".mp4")))
        return DownloadResult(success=True, media_files=files, work_dir=work_dir)

    return mocker.patch.object(inline, "download_media", side_effect=make)


def _query(bot: Any, text: str = URL) -> tg_types.InlineQuery:
    query = tg_types.InlineQuery(id="1", from_user=USER, query=text, offset="")
    return query.as_(bot)


def _only(sequence: list[Any]) -> Any:
    assert len(sequence) == 1
    return sequence[0]


def _requests(bot: Any) -> list[Any]:
    return [call.args[0] for call in bot.call_args_list]


def _answer(bot: Any) -> methods.AnswerInlineQuery:
    answers = [req for req in _requests(bot) if isinstance(req, methods.AnswerInlineQuery)]
    answer: methods.AnswerInlineQuery = _only(answers)
    return answer


def _edited_row(bot: Any) -> list[tg_types.InlineKeyboardButton]:
    markup = bot.edit_message_media.call_args.kwargs["reply_markup"]
    row: list[tg_types.InlineKeyboardButton] = markup.inline_keyboard[0]
    return row


async def _finish_jobs() -> None:
    tasks = [job.task for job in inline._jobs.values() if job.task]
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_cache_miss_is_answered_at_once_with_placeholder(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_download(url: str) -> DownloadResult:
        started.set()
        await release.wait()
        return DownloadResult(success=False, error="stopped")

    mocker.patch.object(inline, "download_media", side_effect=slow_download)

    await inline.on_inline_query(_query(bot), bot)

    answer = _answer(bot)
    assert answer.cache_time == 0
    assert answer.is_personal is True
    article = _only(answer.results)
    assert isinstance(article, tg_types.InlineQueryResultArticle)
    assert article.id == PLACEHOLDER_PREFIX + ui.link_key(URL)
    assert article.reply_markup is not None
    button = article.reply_markup.inline_keyboard[0][0]
    assert button.callback_data == REFRESH_PREFIX + ui.link_key(URL)
    assert await get_inline_link(ui.link_key(URL)) == URL
    await asyncio.wait_for(started.wait(), timeout=1)
    release.set()
    await _finish_jobs()


async def test_cache_hit_returns_media_directly(bot: Any, mocker: MockerFixture) -> None:
    await set_cached_media(URL, [{"type": "video", "file_id": "cached-id"}])
    download = mocker.patch.object(inline, "download_media")

    await inline.on_inline_query(_query(bot), bot)

    answer = _answer(bot)
    cached_video = _only(answer.results)
    assert isinstance(cached_video, tg_types.InlineQueryResultCachedVideo)
    assert cached_video.video_file_id == "cached-id"
    assert answer.cache_time == 300
    download.assert_not_called()


async def test_sent_placeholder_is_replaced_with_video(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    _download(tmp_path, mocker, ["clip.mp4"])
    await inline.on_inline_query(_query(bot), bot)
    chosen = tg_types.ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + ui.link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await inline.on_placeholder_sent(chosen, bot)

    media = bot.edit_message_media.call_args.args[0]
    assert isinstance(media, tg_types.InputMediaVideo)
    assert media.media == "video-id"
    assert bot.edit_message_media.call_args.kwargs == {
        "inline_message_id": "msg-1",
        "reply_markup": None,
    }
    bot.edit_message_reply_markup.assert_awaited_once_with(inline_message_id="msg-1")
    assert await get_cached_media(URL) == [{"type": "video", "file_id": "video-id"}]
    assert not (tmp_path / "work").exists()


async def test_carousel_placeholder_becomes_first_file_and_caches_all(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    _download(tmp_path, mocker, ["1.jpg", "2.jpg"])
    await inline.on_inline_query(_query(bot), bot)
    chosen = tg_types.ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + ui.link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await inline.on_placeholder_sent(chosen, bot)

    media = bot.edit_message_media.call_args.args[0]
    assert isinstance(media, tg_types.InputMediaPhoto)
    assert media.caption is None
    row = _edited_row(bot)
    assert [button.text for button in row] == ["◀️", "1 / 2", "▶️"]
    assert row[2].callback_data == f"{PAGE_PREFIX}{ui.link_key(URL)}:1"
    bot.edit_message_reply_markup.assert_not_called()
    cached = await get_cached_media(URL)
    assert cached is not None
    assert len(cached) == 2


async def test_query_and_delivery_share_one_download(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    download = _download(tmp_path, mocker, ["clip.mp4"])
    await inline.on_inline_query(_query(bot), bot)
    await inline.on_inline_query(_query(bot), bot)
    chosen = tg_types.ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + ui.link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await inline.on_placeholder_sent(chosen, bot)

    assert download.call_count == 1
    assert bot.send_video.await_count == 1


async def test_failed_download_is_shown_with_retry_button(bot: Any, mocker: MockerFixture) -> None:
    mocker.patch.object(
        inline,
        "download_media",
        return_value=DownloadResult(success=False, error="<login> required"),
    )
    await inline.on_inline_query(_query(bot), bot)
    chosen = tg_types.ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + ui.link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await inline.on_placeholder_sent(chosen, bot)

    bot.edit_message_media.assert_not_called()
    text = bot.edit_message_text.call_args.args[0]
    assert "&lt;login&gt; required" in text
    keyboard = bot.edit_message_text.call_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].text == "🔁 Повторить"


async def test_refresh_button_delivers_from_cache(bot: Any) -> None:
    await set_cached_media(URL, [{"type": "photo", "file_id": "cached-photo"}])
    await save_inline_link(ui.link_key(URL), URL)
    callback = tg_types.CallbackQuery(
        id="7",
        from_user=USER,
        chat_instance="x",
        data=REFRESH_PREFIX + ui.link_key(URL),
        inline_message_id="msg-2",
    ).as_(bot)

    await inline.on_refresh(callback, bot)

    media = bot.edit_message_media.call_args.args[0]
    assert isinstance(media, tg_types.InputMediaPhoto)
    assert media.media == "cached-photo"


async def test_refresh_with_unknown_link_asks_to_resend(bot: Any) -> None:
    callback = tg_types.CallbackQuery(
        id="7",
        from_user=USER,
        chat_instance="x",
        data=f"{REFRESH_PREFIX}missing",
        inline_message_id="msg-2",
    ).as_(bot)

    await inline.on_refresh(callback, bot)

    answer = _only(_requests(bot))
    assert isinstance(answer, methods.AnswerCallbackQuery)
    assert answer.show_alert is True
    bot.edit_message_media.assert_not_called()


async def test_keyboard_already_removed_is_not_an_error(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    _download(tmp_path, mocker, ["clip.mp4"])
    bot.edit_message_reply_markup.side_effect = exceptions.TelegramBadRequest(
        method=mocker.Mock(), message="message is not modified"
    )
    await save_inline_link(ui.link_key(URL), URL)
    chosen = tg_types.ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + ui.link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await inline.on_placeholder_sent(chosen, bot)

    bot.edit_message_media.assert_awaited_once()
    assert all("❌" not in call.args[0] for call in bot.edit_message_text.call_args_list)


def _page_callback(bot: Any, payload: str) -> tg_types.CallbackQuery:
    return tg_types.CallbackQuery(
        id="9", from_user=USER, chat_instance="x", data=payload, inline_message_id="msg-3"
    ).as_(bot)


async def test_pager_flips_to_requested_file_and_wraps(bot: Any) -> None:
    key = ui.link_key(URL)
    await save_inline_link(key, URL)
    await set_cached_media(
        URL,
        [{"type": "photo", "file_id": "first"}, {"type": "video", "file_id": "second"}],
    )

    await inline.on_page(_page_callback(bot, f"{PAGE_PREFIX}{key}:1"), bot)

    media = bot.edit_message_media.call_args.args[0]
    assert isinstance(media, tg_types.InputMediaVideo)
    assert media.media == "second"
    row = _edited_row(bot)
    assert row[1].text == "2 / 2"
    assert row[2].callback_data == f"{PAGE_PREFIX}{key}:0"


async def test_cached_carousel_results_carry_the_pager(bot: Any) -> None:
    await set_cached_media(
        URL, [{"type": "photo", "file_id": "first"}, {"type": "photo", "file_id": "second"}]
    )

    await inline.on_inline_query(_query(bot), bot)

    second = _answer(bot).results[1]
    assert second.reply_markup is not None
    pager_row = second.reply_markup.inline_keyboard[0]
    assert pager_row[1].text == "2 / 2"


async def test_pager_for_forgotten_post_asks_to_resend(bot: Any) -> None:
    await inline.on_page(_page_callback(bot, f"{PAGE_PREFIX}missing:1"), bot)

    bot.edit_message_media.assert_not_called()
    answer = _only(_requests(bot))
    assert isinstance(answer, methods.AnswerCallbackQuery)
    assert answer.show_alert is True


async def test_pager_works_for_post_cached_outside_inline(bot: Any) -> None:
    """A carousel cached by the chat handler has no stored link until it is queried."""
    await set_cached_media(
        URL, [{"type": "photo", "file_id": "first"}, {"type": "photo", "file_id": "second"}]
    )
    await inline.on_inline_query(_query(bot), bot)
    markup: Any = _answer(bot).results[0].reply_markup
    next_button = markup.inline_keyboard[0][2]

    await inline.on_page(_page_callback(bot, next_button.callback_data), bot)

    media = bot.edit_message_media.call_args.args[0]
    assert media.media == "second"


async def test_failed_status_edit_does_not_cancel_delivery(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    uploading = asyncio.Event()
    release = asyncio.Event()

    async def slow_upload(**kwargs: Any) -> Any:
        uploading.set()
        await release.wait()
        return SimpleNamespace(video=SimpleNamespace(file_id="video-id"))

    async def flood(*args: Any, **kwargs: Any) -> None:
        release.set()
        raise exceptions.TelegramRetryAfter(
            method=mocker.Mock(), message="Flood control", retry_after=5
        )

    _download(tmp_path, mocker, ["clip.mp4"])
    bot.send_video.side_effect = slow_upload
    bot.edit_message_text.side_effect = flood
    await inline.on_inline_query(_query(bot), bot)
    await asyncio.wait_for(uploading.wait(), timeout=1)
    chosen = tg_types.ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + ui.link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await inline.on_placeholder_sent(chosen, bot)

    bot.edit_message_text.assert_awaited()
    media = bot.edit_message_media.call_args.args[0]
    assert media.media == "video-id"


async def test_telegram_outage_on_replace_offers_retry(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    _download(tmp_path, mocker, ["clip.mp4"])
    bot.edit_message_media.side_effect = exceptions.TelegramNetworkError(
        method=mocker.Mock(), message="timeout"
    )
    await save_inline_link(ui.link_key(URL), URL)
    chosen = tg_types.ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + ui.link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await inline.on_placeholder_sent(chosen, bot)

    keyboard = bot.edit_message_text.call_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].text == TEXT_RETRY
    assert await get_cached_media(URL) == [{"type": "video", "file_id": "video-id"}]


async def test_too_many_preparations_are_refused(
    bot: Any, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inline, "MAX_ACTIVE_JOBS", 1)
    release = asyncio.Event()

    async def slow_download(url: str) -> DownloadResult:
        await release.wait()
        return DownloadResult(success=False, error="stopped")

    download = mocker.patch.object(inline, "download_media", side_effect=slow_download)
    await inline.on_inline_query(_query(bot), bot)
    bot.reset_mock()

    await inline.on_inline_query(_query(bot, "https://www.instagram.com/reel/OTHERLINK11"), bot)

    answer = _answer(bot)
    assert answer.results == []
    assert answer.button is not None
    assert len(inline._jobs) == 1
    release.set()
    await _finish_jobs()
    assert download.call_count == 1
