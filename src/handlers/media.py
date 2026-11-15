from contextlib import AsyncExitStack

import structlog
from aiogram import Router
from aiogram.types import Message

from constants import URL_PATTERN
from handlers.delivery import deliver_url
from inflight import url_lock
from timing import StageTimer, new_request_id
from utils import clean_url

log = structlog.get_logger()

router = Router(name="media")


def _extract_urls(text: str) -> list[str]:
    return [clean_url(raw.strip()) for raw in URL_PATTERN.findall(text)]


async def _process_url(message: Message, url: str) -> None:
    timer = StageTimer()
    with structlog.contextvars.bound_contextvars(req_id=new_request_id()):
        async with AsyncExitStack() as stack:
            with timer.stage("queue"):
                await stack.enter_async_context(url_lock(url))
            await deliver_url(message, url, timer)


@router.message()
async def on_message(message: Message) -> None:
    """Reply to links in a message.

    A placeholder sent through this bot's own inline mode carries the link in
    its text; the inline flow replaces that message itself, so it is ignored.
    """
    if not message.text:
        return

    if message.via_bot and message.bot and message.via_bot.id == message.bot.id:
        return

    for url in _extract_urls(message.text):
        await _process_url(message, url)  # noqa: WPS476
