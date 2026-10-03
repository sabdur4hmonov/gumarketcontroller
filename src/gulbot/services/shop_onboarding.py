"""Writing a shop whose owner has just finished onboarding.

THE ONLY WRITE THE ONBOARDING CONVERSATION MAKES. Everything the owner gives --
name, bot token, channel, admin group, phone -- is held in the conversation
(the token as ciphertext) until the last answer, then written here, in one
transaction. So a bad token, an unreachable channel, a cancel or a drop-off
leaves nothing behind: no half-configured shop for the pollers and the ticks
to pick up and fail on.

The token goes through `set_shop_bot_token`, the one encrypt-on-write path, so
the new shop's `bot_telegram_id` is recorded and its UNIQUE constraint decides
any race between two owners registering the same bot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.services.shop_tokens import set_shop_bot_token


@dataclass(frozen=True)
class NewShop:
    """What a finished onboarding knows. The token is plaintext only for the
    length of the write, and is excluded from repr."""

    name: str
    token: str = field(repr=False)
    channel_id: int
    group_chat_id: int
    owner_telegram_id: int
    owner_phone: str
    owner_phone_verified: bool


async def bot_is_taken(session: AsyncSession, *, bot_id: int) -> bool:
    """Whether a shop already holds this bot. A courtesy for the conversation;
    the UNIQUE constraint is the guarantee."""
    found = await session.scalar(select(Shop.id).where(Shop.bot_telegram_id == bot_id).limit(1))
    return found is not None


async def create_onboarded_shop(session: AsyncSession, new: NewShop) -> int:
    """Insert the shop and store its token. Returns the new shop's id.

    Does not commit. Any failure -- a malformed token, a bot another shop
    registered a moment ago -- propagates, and the caller's rollback takes the
    row with it.

    Never `uses_process_bot_token`: that belongs to the single pilot shop the
    per-shop-token migration found, and no shop created since may have it.
    """
    shop = Shop(
        name=new.name,
        working_hours=DEFAULT_WORKING_HOURS,
        channel_id=new.channel_id,
        group_chat_id=new.group_chat_id,
        owner_telegram_ids=[new.owner_telegram_id],
        owner_phone=new.owner_phone,
        owner_phone_verified=new.owner_phone_verified,
        uses_process_bot_token=False,
    )
    session.add(shop)
    await session.flush()
    await set_shop_bot_token(session, shop_id=shop.id, token=new.token)
    return int(shop.id)
