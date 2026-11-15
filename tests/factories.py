"""polyfactory factories with cheap generation: optional fields stay unset.

Pydantic (aiogram) factories use the models' own defaults, so only required fields are
generated; override anything a test cares about through ``build(field=value)``.
"""

from datetime import UTC, datetime
from pathlib import Path

from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Chat, ChosenInlineResult, InlineQuery, Message, User
from polyfactory import Use
from polyfactory.factories import DataclassFactory
from polyfactory.factories.pydantic_factory import ModelFactory

from downloader.gallery import DownloadResult, MediaFile


class UserFactory(ModelFactory[User]):
    """A human user: ``is_bot=False``, random ``id`` and ``first_name``, nothing else."""

    __model__ = User
    __use_defaults__ = True

    is_bot = False


class ChatFactory(ModelFactory[Chat]):
    """A private chat with a random ``id``."""

    __model__ = Chat
    __use_defaults__ = True

    type = ChatType.PRIVATE


class MessageFactory(ModelFactory[Message]):
    """An unbound message in a private chat; ``text`` and ``from_user`` are unset."""

    __model__ = Message
    __use_defaults__ = True

    date = Use(lambda: datetime.now(UTC))
    chat = Use(ChatFactory.build)


class InlineQueryFactory(ModelFactory[InlineQuery]):
    """An unbound inline query from a random user with a random query string."""

    __model__ = InlineQuery
    __use_defaults__ = True

    from_user = Use(UserFactory.build)


class ChosenInlineResultFactory(ModelFactory[ChosenInlineResult]):
    """A chosen inline result from a random user; ``inline_message_id`` is unset."""

    __model__ = ChosenInlineResult
    __use_defaults__ = True

    from_user = Use(UserFactory.build)


class CallbackQueryFactory(ModelFactory[CallbackQuery]):
    """An unbound callback query from a random user; ``data`` and message ids are unset."""

    __model__ = CallbackQuery
    __use_defaults__ = True

    from_user = Use(UserFactory.build)


class MediaFileFactory(DataclassFactory[MediaFile]):
    """A media file with a random relative path (nothing is created on disk)."""

    __model__ = MediaFile

    path = Use(lambda: Path(MediaFileFactory.__faker__.pystr()))


class DownloadResultFactory(DataclassFactory[DownloadResult]):
    """A successful result: no files, no error, no work directory, no timings."""

    __model__ = DownloadResult
    __use_defaults__ = True

    success = True
    media_files = Use(list[MediaFile])
    error = ""
    work_dir = None
    timings = Use(dict[str, float])
