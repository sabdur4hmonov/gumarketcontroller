"""Drive the REAL dispatcher without touching Telegram or leaking writes.

Two things make this a genuine test of the bot rather than of a mock:

* Updates go through `Dispatcher.feed_update`, so middlewares, router order and
  filters all run exactly as in production.
* The session factory is bound to the test's own connection with
  `join_transaction_mode="create_savepoint"`, so handler code may call
  `session.commit()` for real while every write still disappears on rollback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import (
    CallbackQuery,
    Chat,
    Contact,
    Location,
    Message,
    PhotoSize,
    Update,
    User,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

TEST_TOKEN = "42:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN"


class RecordingSession(BaseSession):
    """Records outgoing API calls instead of performing them."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    @property
    def sent_texts(self) -> list[str]:
        return [c.text for c in self.calls if getattr(c, "text", None) is not None]

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109  aiogram's BaseSession contract
    ) -> Any:
        self.calls.append(method)
        return Message(
            message_id=len(self.calls),
            date=datetime.now(tz=UTC),
            chat=Chat(id=getattr(method, "chat_id", 1), type="private"),
            from_user=User(id=int(TEST_TOKEN.split(":")[0]), is_bot=True, first_name="bot"),
            text=getattr(method, "text", ""),
        )

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def make_bot() -> tuple[Bot, RecordingSession]:
    session = RecordingSession()
    return Bot(token=TEST_TOKEN, session=session), session


def bound_session_factory(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Sessions that join the test's transaction via savepoints."""
    return async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


def text_update(text: str, *, user_id: int, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(tz=UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Aziz"),
            text=text,
        ),
    )


def callback_update(data: str, *, user_id: int, update_id: int = 1, message_id: int = 1) -> Update:
    """An inline button tap, carrying the message it was attached to."""
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb{update_id}",
            from_user=User(id=user_id, is_bot=False, first_name="Aziz"),
            chat_instance=f"chat{user_id}",
            data=data,
            message=Message(
                message_id=message_id,
                date=datetime.now(tz=UTC),
                chat=Chat(id=user_id, type="private"),
                from_user=User(id=1, is_bot=True, first_name="bot"),
                text="carrier",
            ),
        ),
    )


#: Stands in for the shop's catalogue channel. Negative, like a real one.
CHANNEL_ID = -1001234567890


def photo_sizes(file_id: str) -> list[PhotoSize]:
    """Telegram sends several sizes of the same photo, smallest first.

    Two of them here on purpose: the indexer keeps the LAST, and a single-entry
    list would let a bug that takes photo[0] pass unnoticed.
    """
    return [
        PhotoSize(file_id=f"{file_id}-thumb", file_unique_id=f"{file_id}-tu", width=90, height=90),
        PhotoSize(file_id=file_id, file_unique_id=f"{file_id}-u", width=1280, height=1280),
    ]


def channel_message(
    *,
    message_id: int,
    caption: str | None = None,
    media_group_id: str | None = None,
    file_id: str | None = None,
    text: str | None = None,
    chat_id: int = CHANNEL_ID,
) -> Message:
    """A channel post. No from_user: channel posts carry a sender CHAT."""
    return Message(
        message_id=message_id,
        date=datetime.now(tz=UTC),
        chat=Chat(id=chat_id, type="channel"),
        caption=caption,
        media_group_id=media_group_id,
        photo=photo_sizes(file_id) if file_id else None,
        text=text,
    )


def channel_post_update(update_id: int = 1, **kwargs: Any) -> Update:
    return Update(update_id=update_id, channel_post=channel_message(**kwargs))


def edited_channel_post_update(update_id: int = 1, **kwargs: Any) -> Update:
    return Update(update_id=update_id, edited_channel_post=channel_message(**kwargs))


def contact_update(
    *,
    user_id: int,
    phone_number: str = "+998901234567",
    contact_user_id: int | None = None,
    update_id: int = 1,
) -> Update:
    """A shared contact, as Telegram's request_contact button produces one.

    `contact_user_id` defaults to the SENDER, which is what the button gives.
    Passing a different id models the customer picking a friend out of their
    address book instead -- Telegram allows it, and it must not be stored as
    this customer's number.
    """
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(tz=UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Aziz"),
            contact=Contact(
                phone_number=phone_number,
                first_name="Aziz",
                user_id=user_id if contact_user_id is None else contact_user_id,
            ),
        ),
    )


def location_update(
    *, user_id: int, latitude: float, longitude: float, update_id: int = 1
) -> Update:
    """A shared location pin. Not text, so it must not be caught by a
    text-waiting handler."""
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(tz=UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Aziz"),
            location=Location(latitude=latitude, longitude=longitude),
        ),
    )


async def feed(dispatcher: Dispatcher, bot: Bot, update: Update) -> None:
    await dispatcher.feed_update(bot, update)
