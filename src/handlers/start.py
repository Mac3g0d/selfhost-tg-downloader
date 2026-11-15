from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from constants import WELCOME_TEXT

router = Router(name="start")


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT)
