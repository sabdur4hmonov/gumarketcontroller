"""Can a shop's OWN bot actually work in the chat its owner named?

Asked of the shop's bot, never the platform bot: the platform bot's access
proves nothing about the bot that will index the channel and post order cards.

CHANNEL -- the bot must be an ADMINISTRATOR. Telegram delivers `channel_post`
to a bot only then, and the indexer (bot/channel.py) sees nothing otherwise;
CP8 spent two rounds of diagnosis learning that. Checked by READING membership,
because a test post would land in the shop's customer-facing channel. The
indexer itself verifies nothing -- it indexes whatever reaches it -- so this is
the first check of a channel in the codebase, not a second one.

GROUP -- the bot must be an administrator AND must actually post. The second
half is scripts/verify_group.py's rule, "presence is not permission": a
permissions read can succeed while a send fails, and the send is what the
order tick does. Admin is required as well because the shop answers order
cards there, and a bot that is not an admin, with privacy mode on, does not
see a typed rejection reason.

NOTHING RAISES. Every outcome is a `Problem`, so the conversation can tell the
owner exactly what to fix -- and a token Telegram rejects outright is reported
as such, because that is the first place a well-formed but fake token shows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import (
    ClientDecodeError,
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramUnauthorizedError,
)

log = logging.getLogger("gulbot.bot.chat_checks")

ADMIN_STATUSES = frozenset({ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR})
GROUP_TYPES = frozenset({ChatType.GROUP, ChatType.SUPERGROUP})


class Problem(StrEnum):
    TOKEN_REJECTED = "token_rejected"
    NOT_FOUND = "not_found"
    WRONG_TYPE = "wrong_type"
    NOT_ADMIN = "not_admin"
    CANNOT_POST = "cannot_post"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class ChatCheck:
    chat_id: int | None = None
    title: str = ""
    problem: Problem | None = None

    @property
    def ok(self) -> bool:
        return self.problem is None


def _classify(exc: Exception, *, missing: Problem) -> Problem:
    """What a Telegram failure means for the owner. Logged by type only --
    the request URL carries the token."""
    if isinstance(exc, TelegramUnauthorizedError):
        return Problem.TOKEN_REJECTED
    if isinstance(exc, TelegramForbiddenError):
        return Problem.NOT_ADMIN
    if isinstance(exc, TelegramBadRequest):
        return missing
    return Problem.UNREACHABLE


async def _membership(
    bot: Bot, ref: int | str, *, kinds: frozenset[ChatType]
) -> tuple[ChatCheck, int | None]:
    """Resolve the chat and the bot's own standing in it."""
    try:
        chat = await bot.get_chat(ref)
    except (TelegramAPIError, ClientDecodeError) as exc:
        log.info("chat check: get_chat failed: %s", type(exc).__name__)
        problem = (
            Problem.UNREACHABLE
            if isinstance(exc, (TelegramNetworkError, ClientDecodeError))
            else _classify(exc, missing=Problem.NOT_FOUND)
        )
        return ChatCheck(problem=problem), None
    title = chat.title or ""
    if chat.type not in kinds:
        return ChatCheck(chat_id=chat.id, title=title, problem=Problem.WRONG_TYPE), None
    try:
        standing = await bot.get_chat_member(chat.id, bot.id)
    except (TelegramAPIError, ClientDecodeError) as exc:
        log.info("chat check: get_chat_member failed: %s", type(exc).__name__)
        problem = (
            Problem.UNREACHABLE
            if isinstance(exc, (TelegramNetworkError, ClientDecodeError))
            else _classify(exc, missing=Problem.NOT_ADMIN)
        )
        return ChatCheck(chat_id=chat.id, title=title, problem=problem), None
    if standing.status not in ADMIN_STATUSES:
        return ChatCheck(chat_id=chat.id, title=title, problem=Problem.NOT_ADMIN), None
    return ChatCheck(chat_id=chat.id, title=title), chat.id


async def check_channel(bot: Bot, ref: int | str) -> ChatCheck:
    """`ref` is an @username or a numeric chat id. Never posts."""
    result, _ = await _membership(bot, ref, kinds=frozenset({ChatType.CHANNEL}))
    return result


async def check_group_standing(bot: Bot, chat_id: int) -> ChatCheck:
    """The bot is an admin of the group. NEVER posts -- for the 10-minute
    health snapshot (CP18), where a test message would be 144 posts a day."""
    result, _ = await _membership(bot, chat_id, kinds=GROUP_TYPES)
    return result


async def check_group(bot: Bot, chat_id: int, *, test_text: str) -> ChatCheck:
    """Admin, then a real post of `test_text` -- verify_group.py's check."""
    result, resolved = await _membership(bot, chat_id, kinds=GROUP_TYPES)
    if resolved is None:
        return result
    try:
        await bot.send_message(resolved, test_text)
    except (TelegramAPIError, ClientDecodeError) as exc:
        log.info("group check: test post failed: %s", type(exc).__name__)
        problem = (
            Problem.UNREACHABLE
            if isinstance(exc, (TelegramNetworkError, ClientDecodeError))
            else Problem.TOKEN_REJECTED
            if isinstance(exc, TelegramUnauthorizedError)
            else Problem.CANNOT_POST
        )
        return ChatCheck(chat_id=resolved, title=result.title, problem=problem)
    return result
