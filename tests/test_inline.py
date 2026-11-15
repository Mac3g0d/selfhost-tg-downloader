import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, AnswerInlineQuery
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedVideo,
    InputMediaPhoto,
    InputMediaVideo,
    User,
)
from pytest_mock import MockerFixture

from config import settings
from database import (
    get_cached_media,
    get_inline_link,
    init_db,
    save_inline_link,
    set_cached_media,
)
from downloader.gallery import DownloadResult, MediaFile
from handlers import inline
from handlers.inline import (
    PLACEHOLDER_PREFIX,
    REFRESH_PREFIX,
    _link_key,
    on_inline_query,
    on_placeholder_sent,
    on_refresh,
)

URL = "https://www.instagram.com/reel/ABCDEFGHIJK"
USER = User(id=42, is_bot=False, first_name="Tester")


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


def _query(bot: Any, text: str = URL) -> InlineQuery:
    return InlineQuery(id="1", from_user=USER, query=text, offset="").as_(bot)


def _answer(bot: Any) -> AnswerInlineQuery:
    calls = [c.args[0] for c in bot.call_args_list if isinstance(c.args[0], AnswerInlineQuery)]
    assert len(calls) == 1
    return calls[0]


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

    await on_inline_query(_query(bot), bot)

    answer = _answer(bot)
    assert answer.cache_time == 0
    assert answer.is_personal is True
    (result,) = answer.results
    assert isinstance(result, InlineQueryResultArticle)
    assert result.id == PLACEHOLDER_PREFIX + _link_key(URL)
    assert result.reply_markup is not None
    button = result.reply_markup.inline_keyboard[0][0]
    assert button.callback_data == REFRESH_PREFIX + _link_key(URL)
    assert await get_inline_link(_link_key(URL)) == URL
    await asyncio.wait_for(started.wait(), timeout=1)
    release.set()
    await _finish_jobs()


async def test_cache_hit_returns_media_directly(bot: Any, mocker: MockerFixture) -> None:
    await set_cached_media(URL, [{"type": "video", "file_id": "cached-id"}])
    download = mocker.patch.object(inline, "download_media")

    await on_inline_query(_query(bot), bot)

    answer = _answer(bot)
    (result,) = answer.results
    assert isinstance(result, InlineQueryResultCachedVideo)
    assert result.video_file_id == "cached-id"
    assert answer.cache_time == 300
    download.assert_not_called()


async def test_sent_placeholder_is_replaced_with_video(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    _download(tmp_path, mocker, ["clip.mp4"])
    await on_inline_query(_query(bot), bot)
    chosen = ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + _link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await on_placeholder_sent(chosen, bot)

    media = bot.edit_message_media.call_args.args[0]
    assert isinstance(media, InputMediaVideo)
    assert media.media == "video-id"
    assert bot.edit_message_media.call_args.kwargs == {"inline_message_id": "msg-1"}
    bot.edit_message_reply_markup.assert_awaited_once_with(inline_message_id="msg-1")
    assert await get_cached_media(URL) == [{"type": "video", "file_id": "video-id"}]
    assert not (tmp_path / "work").exists()


async def test_carousel_placeholder_becomes_first_file_and_caches_all(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    _download(tmp_path, mocker, ["1.jpg", "2.jpg"])
    await on_inline_query(_query(bot), bot)
    chosen = ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + _link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await on_placeholder_sent(chosen, bot)

    media = bot.edit_message_media.call_args.args[0]
    assert isinstance(media, InputMediaPhoto)
    assert media.caption == "1 из 2"
    cached = await get_cached_media(URL)
    assert cached is not None
    assert len(cached) == 2


async def test_query_and_delivery_share_one_download(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    download = _download(tmp_path, mocker, ["clip.mp4"])
    await on_inline_query(_query(bot), bot)
    await on_inline_query(_query(bot), bot)
    chosen = ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + _link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await on_placeholder_sent(chosen, bot)

    assert download.call_count == 1
    assert bot.send_video.await_count == 1


async def test_failed_download_is_shown_with_retry_button(bot: Any, mocker: MockerFixture) -> None:
    mocker.patch.object(
        inline,
        "download_media",
        return_value=DownloadResult(success=False, error="<login> required"),
    )
    await on_inline_query(_query(bot), bot)
    chosen = ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + _link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await on_placeholder_sent(chosen, bot)

    bot.edit_message_media.assert_not_called()
    text = bot.edit_message_text.call_args.args[0]
    assert "&lt;login&gt; required" in text
    keyboard = bot.edit_message_text.call_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].text == "🔁 Повторить"


async def test_refresh_button_delivers_from_cache(bot: Any) -> None:
    await set_cached_media(URL, [{"type": "photo", "file_id": "cached-photo"}])
    await save_inline_link(_link_key(URL), URL)
    callback = CallbackQuery(
        id="7",
        from_user=USER,
        chat_instance="x",
        data=REFRESH_PREFIX + _link_key(URL),
        inline_message_id="msg-2",
    ).as_(bot)

    await on_refresh(callback, bot)

    media = bot.edit_message_media.call_args.args[0]
    assert isinstance(media, InputMediaPhoto)
    assert media.media == "cached-photo"


async def test_refresh_with_unknown_link_asks_to_resend(bot: Any) -> None:
    callback = CallbackQuery(
        id="7",
        from_user=USER,
        chat_instance="x",
        data=REFRESH_PREFIX + "missing",
        inline_message_id="msg-2",
    ).as_(bot)

    await on_refresh(callback, bot)

    (answer,) = [c.args[0] for c in bot.call_args_list]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.show_alert is True
    bot.edit_message_media.assert_not_called()


async def test_keyboard_already_removed_is_not_an_error(
    bot: Any, tmp_path: Path, mocker: MockerFixture
) -> None:
    _download(tmp_path, mocker, ["clip.mp4"])
    bot.edit_message_reply_markup.side_effect = TelegramBadRequest(
        method=mocker.Mock(), message="message is not modified"
    )
    await save_inline_link(_link_key(URL), URL)
    chosen = ChosenInlineResult(
        result_id=PLACEHOLDER_PREFIX + _link_key(URL),
        from_user=USER,
        query=URL,
        inline_message_id="msg-1",
    )

    await on_placeholder_sent(chosen, bot)

    bot.edit_message_media.assert_awaited_once()
    assert all("❌" not in call.args[0] for call in bot.edit_message_text.call_args_list)
