from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router(name="start")

WELCOME_TEXT = (
    "👋 <b>Привет!</b>\n\n"
    "Я скачиваю видео из <b>TikTok</b> и <b>Instagram</b>.\n\n"
    "Просто отправь мне ссылку — я скачаю и пришлю видео прямо сюда.\n\n"
    "🔗 <b>Поддерживаемые ссылки:</b>\n"
    "• <code>tiktok.com</code> / <code>vm.tiktok.com</code>\n"
    "• <code>instagram.com/reel/...</code>\n"
    "• <code>instagram.com/p/...</code>"
)


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT)
