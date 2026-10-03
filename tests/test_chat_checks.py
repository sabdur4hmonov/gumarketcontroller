"""Can THIS shop's bot actually work in the chat the owner named?

Two checks, answered by the shop's own bot -- never the platform bot, whose
access proves nothing about the bot that will index the channel and post order
cards.

  CHANNEL  the bot must be an ADMINISTRATOR: Telegram delivers `channel_post`
           to a bot only then, and the indexer sees nothing otherwise (CP8
           learned that the hard way). Checked by READING membership -- a test
           post would land in the shop's customer-facing channel.
  GROUP    the bot must be an administrator AND must actually be able to post:
           the verify_group.py rule, "presence is not permission" -- a
           permissions read can succeed while a send fails, and the send is
           what the order tick does.

Every failure is a named `Problem`, so the conversation can say exactly what to
fix, and nothing raises.
"""

from __future__ import annotations

from typing import Any

from aiogram.methods import GetChat, GetChatMember, SendMessage
from tests.telegram_scripted import (
    CHAT_NOT_FOUND,
    FORBIDDEN,
    UNAUTHORIZED,
    Reply,
    chat,
    error,
    member,
    ok,
    scripted_bot,
    sent_message,
)

from gulbot.bot.chat_checks import Problem, check_channel, check_group

TOKEN = "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
BOT_ID = 111111
CHANNEL, GROUP = -1_001_000_000_001, -1_001_000_000_002


def answers(
    *, get_chat: Reply | None = None, get_member: Reply | None = None, send: Reply | None = None
) -> Any:
    def script(method: Any) -> Reply:
        if isinstance(method, GetChat) and get_chat is not None:
            return get_chat
        if isinstance(method, GetChatMember) and get_member is not None:
            return get_member
        if isinstance(method, SendMessage) and send is not None:
            return send
        raise AssertionError(f"unexpected call {type(method).__name__}")

    return script


# --- channel ---------------------------------------------------------------


async def test_a_channel_where_the_bot_is_admin_passes_by_username() -> None:
    bot, session = scripted_bot(
        TOKEN,
        answers(
            get_chat=ok(chat(CHANNEL, "channel", title="Lola", username="lola")),
            get_member=ok(member(BOT_ID, "administrator")),
        ),
    )
    result = await check_channel(bot, "@lola")

    assert result.ok and result.problem is None
    assert (result.chat_id, result.title) == (CHANNEL, "Lola")
    # It asked about ITSELF, in the channel it resolved.
    asked = [c for c in session.calls if isinstance(c, GetChatMember)][0]
    assert (asked.chat_id, asked.user_id) == (CHANNEL, BOT_ID)
    assert "SendMessage" not in session.names(), "never posts into the customer channel"


async def test_a_channel_passes_by_numeric_id_too() -> None:
    """A forwarded post gives the id, not the username."""
    bot, _ = scripted_bot(
        TOKEN,
        answers(
            get_chat=ok(chat(CHANNEL, "channel")),
            get_member=ok(member(BOT_ID, "administrator")),
        ),
    )
    assert (await check_channel(bot, CHANNEL)).ok


async def test_a_channel_the_bot_cannot_see_is_not_found() -> None:
    bot, _ = scripted_bot(TOKEN, answers(get_chat=CHAT_NOT_FOUND))
    assert (await check_channel(bot, "@nowhere")).problem is Problem.NOT_FOUND


async def test_a_channel_where_the_bot_is_only_a_member_is_not_enough() -> None:
    bot, _ = scripted_bot(
        TOKEN,
        answers(get_chat=ok(chat(CHANNEL, "channel")), get_member=ok(member(BOT_ID, "member"))),
    )
    assert (await check_channel(bot, CHANNEL)).problem is Problem.NOT_ADMIN


async def test_a_channel_the_bot_left_or_was_kicked_from_is_not_admin() -> None:
    for status in ("left", "kicked"):
        bot, _ = scripted_bot(
            TOKEN,
            answers(get_chat=ok(chat(CHANNEL, "channel")), get_member=ok(member(BOT_ID, status))),
        )
        assert (await check_channel(bot, CHANNEL)).problem is Problem.NOT_ADMIN


async def test_a_group_offered_as_the_channel_is_the_wrong_kind() -> None:
    bot, _ = scripted_bot(TOKEN, answers(get_chat=ok(chat(GROUP, "supergroup"))))
    assert (await check_channel(bot, GROUP)).problem is Problem.WRONG_TYPE


async def test_a_forbidden_channel_is_not_admin() -> None:
    bot, _ = scripted_bot(TOKEN, answers(get_chat=FORBIDDEN))
    assert (await check_channel(bot, CHANNEL)).problem is Problem.NOT_ADMIN


async def test_a_token_telegram_rejects_is_named_as_such() -> None:
    """The first live call is where a well-formed but fake or revoked token
    shows up. The conversation sends the owner back to the token step."""
    bot, _ = scripted_bot(TOKEN, answers(get_chat=UNAUTHORIZED))
    assert (await check_channel(bot, "@lola")).problem is Problem.TOKEN_REJECTED


async def test_telegram_being_unreachable_is_not_blamed_on_the_owner() -> None:
    bot, _ = scripted_bot(TOKEN, answers(get_chat=error(502, "Bad Gateway")))
    assert (await check_channel(bot, "@lola")).problem is Problem.UNREACHABLE


# --- group -----------------------------------------------------------------


async def test_a_group_where_the_bot_is_admin_and_can_post_passes() -> None:
    bot, session = scripted_bot(
        TOKEN,
        answers(
            get_chat=ok(chat(GROUP, "supergroup", title="Buyurtmalar")),
            get_member=ok(member(BOT_ID, "administrator")),
            send=ok(sent_message(GROUP)),
        ),
    )
    result = await check_group(bot, GROUP, test_text="salom")

    assert result.ok and (result.chat_id, result.title) == (GROUP, "Buyurtmalar")
    posted = [c for c in session.calls if isinstance(c, SendMessage)]
    assert [(p.chat_id, p.text) for p in posted] == [(GROUP, "salom")]


async def test_a_group_where_the_bot_is_not_admin_fails_before_posting() -> None:
    bot, session = scripted_bot(
        TOKEN,
        answers(get_chat=ok(chat(GROUP, "group")), get_member=ok(member(BOT_ID, "member"))),
    )
    assert (await check_group(bot, GROUP, test_text="x")).problem is Problem.NOT_ADMIN
    assert "SendMessage" not in session.names()


async def test_an_admin_that_still_cannot_post_fails_the_check() -> None:
    """Presence is not permission: the reason verify_group.py sends."""
    bot, _ = scripted_bot(
        TOKEN,
        answers(
            get_chat=ok(chat(GROUP, "supergroup")),
            get_member=ok(member(BOT_ID, "administrator")),
            send=error(403, "Forbidden: not enough rights to send text messages"),
        ),
    )
    assert (await check_group(bot, GROUP, test_text="x")).problem is Problem.CANNOT_POST


async def test_a_channel_offered_as_the_group_is_the_wrong_kind() -> None:
    bot, _ = scripted_bot(TOKEN, answers(get_chat=ok(chat(CHANNEL, "channel"))))
    assert (await check_group(bot, CHANNEL, test_text="x")).problem is Problem.WRONG_TYPE


async def test_a_group_the_bot_is_not_in_is_not_found() -> None:
    bot, _ = scripted_bot(TOKEN, answers(get_chat=CHAT_NOT_FOUND))
    assert (await check_group(bot, GROUP, test_text="x")).problem is Problem.NOT_FOUND
