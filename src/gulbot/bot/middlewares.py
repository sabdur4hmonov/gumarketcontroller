"""Outer middlewares: chat gate, then database session, then customer identity.

Registered as OUTER middlewares on the update observer so they run once per
update, before any router filtering. An inner middleware would run per matching
handler, opening a session even for updates nothing handles.

ORDER MATTERS. The chat gate is first, so an update from a group never reaches
the session middleware and never reaches the customer middleware -- which would
otherwise register a member of the shop's own admin group as a customer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Chat, TelegramObject, Update, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.bot.states import AdminOrder
from gulbot.i18n import button_labels
from gulbot.i18n.catalog import DEFAULT_LANGUAGE
from gulbot.models.shop import Shop
from gulbot.services.customers import get_or_create_customer
from gulbot.services.shop_language import shop_language

#: Callback data prefix the shop's order-card buttons carry. The ONE thing
#: a group may send that is not dropped, so it is compared here against the
#: factory's own prefix rather than a copy -- `test_admin_orders.py` fails
#: the build if the two drift apart.
ADMIN_CALLBACK_PREFIX = "ordadm"

#: Chat types the bot will act on, as an ALLOW list rather than a block list.
#: A block list would silently start answering in whatever chat type Telegram
#: invents next; this way an unknown type is ignored, which is the safe default
#: for a bot that also sits in the shop's own admin group.
#:
#: "private"  the customer conversation, which is the entire product.
#: "channel"  the shop's catalogue, read by CP8's indexer. Not a conversation:
#:            the channel router only registers channel_post updates, and
#:            nothing there replies.
#:
#: A GROUP is not on this list. What the bot does in the shop's own group is
#: an explicit exception below, not a chat type it serves.
SERVED_CHAT_TYPES = frozenset({"private", "channel"})

GROUP_CHAT_TYPES = frozenset({"group", "supergroup"})


class ChatGateMiddleware(BaseMiddleware):
    """Ignore anything that is not a private chat or the catalogue channel.

    WHY THIS EXISTS. The bot is a member of the shop's admin group so it can
    post order cards there. Without this gate it also ANSWERS there: `/start`
    returned the language picker into the group, every message it received got
    the "choose a button" fallback with a customer keyboard attached, and the
    admin who typed it was registered as a customer of the shop.

    Telegram's privacy mode hid most of that -- while it is on, a bot in a group
    only receives commands, replies and mentions. But `/start` is a command, so
    that half was always visible, and promoting the bot to group administrator
    turns privacy mode off and exposes the rest. Being an admin of your own
    group is a normal thing to do, so this cannot rest on a Telegram setting.

    Dropping the update here rather than filtering per router means a router
    added later cannot forget the rule, and means no database session is opened
    for traffic the bot has no business in.

    THE SHOP'S OWN GROUP, not "a group" (M3 of AUDIT_MULTI_TENANT.md). The
    exception below is for the shop acting on its own order card, so the chat
    must be `shops.group_chat_id`. Until CP-MT2 only the shape of the update
    was checked, and the order router's own chat check was the only thing
    standing between a stranger's group and a handler -- a check every future
    group-reachable handler would have had to remember.
    """

    def __init__(self, *, shop_id: int, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.shop_id = shop_id
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Populated by aiogram's own UserContextMiddleware, which is registered
        # in Dispatcher.__init__ and therefore runs ahead of this one.
        chat: Chat | None = data.get("event_chat")
        if chat is None or chat.type in SERVED_CHAT_TYPES:
            return await handler(event, data)
        if (
            chat.type in GROUP_CHAT_TYPES
            and await self._is_shop_action(event, data)
            and await self._is_the_shops_own_group(chat.id)
        ):
            return await handler(event, data)
        return None

    async def _is_the_shops_own_group(self, chat_id: int) -> bool:
        """Is this group the one the shop's order cards are posted to?

        Asked LAST, after the shape checks, so ordinary group chatter never
        costs a query -- only an order-card tap or a pending rejection reason
        does. A shop with no group lets no group in: NULL is "not set up", not
        "any group". Own short session: this runs before DbSessionMiddleware,
        and the update may yet be dropped.
        """
        async with self.session_factory() as session:
            group = await session.scalar(select(Shop.group_chat_id).where(Shop.id == self.shop_id))
        return group is not None and int(group) == chat_id

    async def _is_shop_action(self, event: TelegramObject, data: dict[str, Any]) -> bool:
        """The narrow exception: the shop acting on its own order card.

        TWO things get through, and nothing else:

          * a tap on an order-card button, recognised by its callback prefix.
            Not "any callback from a group" -- a customer-facing callback
            forwarded into the group would then be answered there, which is
            the same class of bug as the one this gate exists to fix.
          * a message from someone the bot has ALREADY asked for a rejection
            reason. Gated on that person's own FSM state, so it is one
            message from one admin who just tapped Reject -- not group
            chatter, and not another admin's message.

            NOT a command, and NOT a button label, even in that state. Those
            belong to nav and onboarding, whose handlers reply with a CUSTOMER
            keyboard -- posting one into the shop's own group is the very bug
            this gate exists to prevent. Refusing them here is what lets
            `admin_orders` sit after nav (so Cancel and /start stay first
            everywhere, which the shadow sweep enforces) without nav ever
            actually running in a group. Cancel is an inline button on the
            prompt instead.

        Everything else from a group is still dropped before a session is
        opened and before the customer middleware can register an admin as a
        customer.
        """
        if not isinstance(event, Update):  # pragma: no cover - the observer gives Updates
            return False

        callback = event.callback_query
        if callback is not None:
            payload = callback.data or ""
            return payload.startswith(f"{ADMIN_CALLBACK_PREFIX}:")

        if event.message is None or event.message.text is None:
            return False
        body = event.message.text.strip()
        if body.startswith("/") or body in button_labels():
            return False
        # aiogram's FSM middleware is registered in Dispatcher.__init__, so it
        # runs ahead of this one and the context is already here.
        state: FSMContext | None = data.get("state")
        if state is None:  # pragma: no cover - always injected in practice
            return False
        return await state.get_state() == AdminOrder.entering_reject_reason.state


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


class CustomerMiddleware(BaseMiddleware):
    """Resolve the customer for this shop, creating them on first contact.

    NOT IN A GROUP. The shop's own group has no customer in it, and CP13's
    gate exceptions -- a Confirm tap, a typed rejection reason -- arrive here
    with a perfectly ordinary `event_from_user` attached to them: the admin.
    Creating a customer row for that admin is the CP10c bug wearing different
    clothes, and it would be invisible: no error, just a shop slowly acquiring
    its own staff as customers, and eventually reminding them.

    Until CP13 the gate made this unreachable, so the guard sat in one place.
    Now the gate has holes in it on purpose, the rule has to live where the
    question is actually asked.
    """

    def __init__(self, shop_id: int) -> None:
        self.shop_id = shop_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        session: AsyncSession | None = data.get("session")
        chat: Chat | None = data.get("event_chat")
        in_group = chat is not None and chat.type in GROUP_CHAT_TYPES
        if in_group:
            # The shop, not a customer. `lang` is still needed -- the card and
            # its buttons are rendered in it -- so it is the SHOP's language
            # (L2), not read from a customer row that must not exist.
            if "lang" not in data:
                data["lang"] = (
                    await shop_language(session, shop_id=self.shop_id)
                    if session is not None
                    else DEFAULT_LANGUAGE
                )
        elif user is not None and session is not None and not user.is_bot:
            customer, created = await get_or_create_customer(
                session, shop_id=self.shop_id, telegram_user_id=user.id
            )
            data["customer"] = customer
            data["customer_created"] = created
            data["lang"] = customer.lang
        data.setdefault("shop_id", self.shop_id)
        return await handler(event, data)


class PrivateOnlyMiddleware(BaseMiddleware):
    """The PLATFORM bot talks to shop owners in private, and nowhere else.

    Its conversation is one person setting up a shop: there is no group
    exception to make, unlike a shop's own bot and its order cards.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat: Chat | None = data.get("event_chat")
        if chat is not None and chat.type != "private":
            return None
        return await handler(event, data)


class OwnerLanguageMiddleware(BaseMiddleware):
    """`lang` for the platform bot, from the owner's own Telegram language.

    Shop owners are not customers, so there is no customer row to read a
    language from -- and asking first would put a question in front of the one
    the owner came to answer.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        code = (user.language_code or "") if user is not None else ""
        data["lang"] = "ru" if code.lower().startswith("ru") else DEFAULT_LANGUAGE
        return await handler(event, data)
