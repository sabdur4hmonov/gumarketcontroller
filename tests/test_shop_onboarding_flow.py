"""The shop-owner onboarding conversation, driven through the REAL platform
dispatcher.

Everything goes through `Dispatcher.feed_update`, so middlewares, router order
and filters run as in production. The platform bot records what it says; the
NEW shop's bot -- built from the token the owner pastes -- answers with scripted
Bot API JSON, so "can the shop's bot see this channel" is asked and answered the
way Telegram would.

What this file exists to prove, beyond the happy path:

* NO PARTIAL SHOP. The row is written once, at the very end, in one
  transaction. A bad token, an unreachable channel, a group the bot cannot post
  in, a cancel, a drop-off -- none of them leaves a shop behind.
* THE TOKEN NEVER SITS IN PLAINTEXT. The pasted message is deleted, and the
  conversation's own state holds only ciphertext.
* RESUMABLE. /start mid-flow picks up at the step the owner left, with what
  they already gave -- across a process restart too.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import DeleteMessage, GetChat, GetChatMember, SendMessage
from aiogram.types import (
    Chat,
    ChatShared,
    Message,
    MessageOriginChannel,
    ReplyKeyboardMarkup,
    Update,
    User,
)
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import (
    TEST_TOKEN,
    RecordingSession,
    bound_session_factory,
    callback_update,
    contact_update,
    feed,
    text_update,
)
from tests.telegram_scripted import (
    CHAT_NOT_FOUND,
    UNAUTHORIZED,
    Reply,
    ScriptedSession,
    chat,
    error,
    member,
    ok,
    sent_message,
)

import gulbot.bot.factory as factory_module
import gulbot.services.shop_tokens as shop_tokens_module
from gulbot.bot.callbacks import OnboardBrandingCB
from gulbot.bot.factory import build_platform_dispatcher
from gulbot.bot.middlewares import OwnerLanguageMiddleware
from gulbot.bot.routers.shop_onboarding import GROUP_REQUEST_ID
from gulbot.bot.states import ShopOnboarding
from gulbot.config import Settings
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.shop_tokens import decrypt_token, set_shop_bot_token

pytestmark = pytest.mark.infra

OWNER = 5_551_001
PLATFORM_TOKEN = "999999:PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP"
SHOP_TOKEN = "777777:SHOPshopSHOPshopSHOPshopSHOPshopSX"
SHOP_SECRET = SHOP_TOKEN.split(":", 1)[1]
SHOP_BOT_ID = 777777
CHANNEL, GROUP = -1_001_700_000_001, -1_001_700_000_002
CANCEL = CATALOG["btn.nav.cancel"]["uz"]
UZ = "uz"


def _t(key: str, **kwargs: Any) -> str:
    return t(key, UZ, **kwargs)


class ShopTelegram:
    """What the NEW shop's bot will hear back from Telegram. Mutable, so a
    test can fix the owner's setup mid-conversation and try again."""

    def __init__(self) -> None:
        self.channel: Reply = ok(chat(CHANNEL, "channel", title="Lola", username="lola"))
        self.channel_member: Reply = ok(member(SHOP_BOT_ID, "administrator"))
        self.group: Reply = ok(chat(GROUP, "supergroup", title="Buyurtmalar"))
        self.group_member: Reply = ok(member(SHOP_BOT_ID, "administrator"))
        self.group_post: Reply = ok(sent_message(GROUP))
        self.built: list[str | None] = []
        self.sessions: list[ScriptedSession] = []

    def _script(self, method: Any) -> Reply:
        if isinstance(method, GetChat):
            return self.channel if method.chat_id in (CHANNEL, "@lola") else self.group
        if isinstance(method, GetChatMember):
            return self.channel_member if method.chat_id == CHANNEL else self.group_member
        if isinstance(method, SendMessage):
            return self.group_post
        raise AssertionError(f"the shop bot was asked {type(method).__name__}")

    def factory(self, token: str | None) -> Bot:
        self.built.append(token)
        session = ScriptedSession(self._script)
        self.sessions.append(session)
        return Bot(token=token or TEST_TOKEN, session=session)

    def calls(self) -> list[Any]:
        return [call for session in self.sessions for call in session.calls]


class Owner:
    """One shop owner talking to the platform bot."""

    def __init__(self, dispatcher: Dispatcher, bot: Bot, recorder: RecordingSession) -> None:
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self._update = 100

    def _next(self) -> int:
        self._update += 1
        return self._update

    async def send(self, update: Update) -> None:
        await feed(self.dispatcher, self.bot, update)

    async def say(self, body: str) -> None:
        await self.send(text_update(body, user_id=OWNER, update_id=self._next()))

    async def tap(self, data: str) -> None:
        await self.send(callback_update(data, user_id=OWNER, update_id=self._next()))

    async def forward_from_channel(self, chat_id: int) -> None:
        update_id = self._next()
        await self.send(
            Update(
                update_id=update_id,
                message=Message(
                    message_id=update_id,
                    date=datetime.now(tz=UTC),
                    chat=Chat(id=OWNER, type="private"),
                    from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
                    text="Qizil atirgul buketi",
                    forward_origin=MessageOriginChannel(
                        date=datetime.now(tz=UTC),
                        chat=Chat(id=chat_id, type="channel", title="Lola"),
                        message_id=7,
                    ),
                ),
            )
        )

    async def share_group(self, chat_id: int) -> None:
        update_id = self._next()
        await self.send(
            Update(
                update_id=update_id,
                message=Message(
                    message_id=update_id,
                    date=datetime.now(tz=UTC),
                    chat=Chat(id=OWNER, type="private"),
                    from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
                    chat_shared=ChatShared(request_id=GROUP_REQUEST_ID, chat_id=chat_id),
                ),
            )
        )

    async def share_contact(self, *, own: bool = True) -> None:
        await self.send(
            contact_update(
                user_id=OWNER,
                phone_number="+998901112233",
                contact_user_id=None if own else OWNER + 1,
                update_id=self._next(),
            )
        )

    async def state(self) -> str | None:
        return await self._context().get_state()

    async def data(self) -> dict[str, Any]:
        return await self._context().get_data()

    def _context(self):  # type: ignore[no-untyped-def]
        return self.dispatcher.fsm.get_context(bot=self.bot, chat_id=OWNER, user_id=OWNER)

    @property
    def said(self) -> list[str]:
        return self.recorder.sent_texts

    def last_markup(self) -> Any:
        marked = [c for c in self.recorder.calls if getattr(c, "reply_markup", None) is not None]
        return marked[-1].reply_markup if marked else None

    # -- the happy path, step by step -------------------------------------

    async def through_token(self) -> None:
        await self.say("/start")
        await self.say(SHOP_TOKEN)

    async def through_name(self, *, has_branding: bool = False, name: str = "Lola Gullari") -> None:
        await self.through_token()
        await self.tap(OnboardBrandingCB(answer="yes" if has_branding else "no").pack())
        await self.say(name)

    async def through_channel(self) -> None:
        await self.through_name()
        await self.say("@lola")

    async def through_group(self) -> None:
        await self.through_channel()
        await self.share_group(GROUP)

    async def all_the_way(self) -> None:
        await self.through_group()
        await self.share_contact()


@pytest.fixture
def key(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> str:
    fresh = Fernet.generate_key().decode()
    moved = settings.model_copy(update={"shop_token_encryption_key": SecretStr(fresh)})
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: moved)
    return fresh


@pytest.fixture
def process_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """BOT_TOKEN is the pilot's bot; onboarding must never hand it out again."""
    monkeypatch.setattr(factory_module, "get_settings", lambda: Settings(bot_token=TEST_TOKEN))


@pytest.fixture
def storage() -> MemoryStorage:
    """Shared across dispatcher instances, so a 'restart' keeps the state --
    as Redis does in production."""
    return MemoryStorage()


@pytest.fixture
def telegram() -> ShopTelegram:
    return ShopTelegram()


@pytest.fixture
def created() -> list[int]:
    return []


def _platform(
    db: AsyncConnection, storage: BaseStorage, telegram: ShopTelegram, created: list[int]
) -> Owner:
    async def on_shop_created(shop_id: int) -> None:
        created.append(shop_id)

    dispatcher = build_platform_dispatcher(
        session_factory=bound_session_factory(db),
        storage=storage,
        shop_bot_factory=telegram.factory,
        on_shop_created=on_shop_created,
    )
    recorder = RecordingSession()
    return Owner(dispatcher, Bot(token=PLATFORM_TOKEN, session=recorder), recorder)


@pytest_asyncio.fixture
async def owner(
    db: AsyncConnection,
    key: str,
    process_token: None,
    storage: MemoryStorage,
    telegram: ShopTelegram,
    created: list[int],
) -> Owner:
    return _platform(db, storage, telegram, created)


async def _shops(db: AsyncConnection) -> list[Any]:
    return list(
        (
            await db.execute(
                text(
                    "SELECT id, name, channel_id, group_chat_id, owner_telegram_ids, "
                    " owner_phone, owner_phone_verified, uses_process_bot_token, "
                    " bot_token_encrypted, bot_telegram_id, lang FROM shops ORDER BY id"
                )
            )
        ).mappings()
    )


def _no_plaintext_in(storage: MemoryStorage) -> None:
    """Every byte of conversation state, searched for the token's secret."""
    assert SHOP_SECRET not in repr(storage.storage)


# --- step 1: the token ------------------------------------------------------


async def test_start_explains_botfather_and_asks_for_the_token(owner: Owner) -> None:
    await owner.say("/start")
    assert owner.said == [_t("owner.welcome")]
    assert await owner.state() == ShopOnboarding.entering_token.state


@pytest.mark.parametrize(
    "pasted",
    [
        "salom",
        "777777",
        "777777:short",
        "abc:SHOPshopSHOPshopSHOPshopSHOPshopSX",
        "777777:SHOP shopSHOPshopSHOPshopSHOPshopX",
    ],
)
async def test_a_malformed_token_is_refused_and_nothing_is_kept(
    owner: Owner, db: AsyncConnection, storage: MemoryStorage, pasted: str
) -> None:
    before = await _shops(db)
    await owner.say("/start")
    await owner.say(pasted)

    assert owner.said[-1] == _t("owner.token_invalid")
    assert await owner.state() == ShopOnboarding.entering_token.state
    assert await owner.data() == {}
    assert await _shops(db) == before


async def test_a_valid_token_is_kept_only_as_ciphertext_and_the_message_deleted(
    owner: Owner, storage: MemoryStorage
) -> None:
    await owner.through_token()

    _no_plaintext_in(storage)
    data = await owner.data()
    assert decrypt_token(data["token"]) == SHOP_TOKEN
    deleted = [c for c in owner.recorder.calls if isinstance(c, DeleteMessage)]
    assert [(d.chat_id, d.message_id) for d in deleted] == [(OWNER, owner._update)]
    assert await owner.state() == ShopOnboarding.choosing_branding.state


async def test_no_telegram_call_is_made_to_check_the_token(
    owner: Owner, telegram: ShopTelegram
) -> None:
    """Format only at this step, as specified. The first live call is the
    channel check, and that is where a fake token is caught."""
    await owner.through_token()
    assert telegram.built == []


async def test_a_bot_already_serving_a_shop_is_refused(owner: Owner, db: AsyncConnection) -> None:
    taken = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('Taken', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    async with bound_session_factory(db)() as session:
        await set_shop_bot_token(session, shop_id=taken, token=SHOP_TOKEN)
        await session.commit()

    await owner.through_token()

    assert owner.said[-1] == _t("owner.token_taken")
    assert await owner.state() == ShopOnboarding.entering_token.state
    assert await owner.data() == {}


@pytest.mark.parametrize("which", ["pilot", "platform"])
async def test_the_pilot_bot_and_the_platform_bot_cannot_be_registered(
    owner: Owner, which: str
) -> None:
    await owner.say("/start")
    await owner.say(TEST_TOKEN if which == "pilot" else PLATFORM_TOKEN)
    assert owner.said[-1] == _t("owner.token_taken")
    assert await owner.state() == ShopOnboarding.entering_token.state


# --- step 2: branding and the logo prompt ------------------------------------


async def test_no_logo_gets_a_generation_prompt_with_the_shop_name(owner: Owner) -> None:
    await owner.through_name(has_branding=False, name="Lola Gullari")
    assert _t("owner.logo_generate", name="Lola Gullari") in owner.said


async def test_an_existing_logo_gets_an_enhancement_prompt(owner: Owner) -> None:
    await owner.through_name(has_branding=True, name="Lola Gullari")
    assert _t("owner.logo_enhance", name="Lola Gullari") in owner.said
    assert _t("owner.logo_generate", name="Lola Gullari") not in owner.said


async def test_the_shop_name_is_escaped_in_the_prompt(owner: Owner) -> None:
    """User input going into an HTML message."""
    await owner.through_name(name="<b>Gul</b> & Co")
    prompt = next(s for s in owner.said if "Gul" in s and "Co" in s)
    assert "&lt;b&gt;Gul&lt;/b&gt; &amp; Co" in prompt
    assert "<b>Gul</b>" not in prompt


async def test_the_channel_step_follows_the_prompt(owner: Owner) -> None:
    await owner.through_name()
    assert owner.said[-1] == _t("owner.channel_ask")
    assert await owner.state() == ShopOnboarding.waiting_channel.state


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
async def test_an_unusable_shop_name_is_asked_again(owner: Owner, name: str) -> None:
    await owner.through_token()
    await owner.tap(OnboardBrandingCB(answer="no").pack())
    await owner.say(name)
    assert owner.said[-1] == _t("owner.name_invalid")
    assert await owner.state() == ShopOnboarding.entering_shop_name.state


# --- step 3: the channel ---------------------------------------------------


async def test_a_channel_named_by_username_is_checked_by_the_shop_s_own_bot(
    owner: Owner, telegram: ShopTelegram
) -> None:
    await owner.through_channel()

    assert telegram.built == [SHOP_TOKEN], "the SHOP's bot asked, not the platform's"
    asked = [c for c in telegram.calls() if isinstance(c, GetChatMember)]
    assert [(a.chat_id, a.user_id) for a in asked] == [(CHANNEL, SHOP_BOT_ID)]
    assert (await owner.data())["channel_id"] == CHANNEL
    assert _t("owner.posting_guide") in owner.said
    assert await owner.state() == ShopOnboarding.waiting_group.state


async def test_a_forwarded_post_identifies_the_channel(owner: Owner) -> None:
    await owner.through_name()
    await owner.forward_from_channel(CHANNEL)
    assert (await owner.data())["channel_id"] == CHANNEL
    assert await owner.state() == ShopOnboarding.waiting_group.state


async def test_something_that_is_not_a_channel_reference_is_asked_again(
    owner: Owner, telegram: ShopTelegram
) -> None:
    await owner.through_name()
    await owner.say("mening kanalim")
    assert owner.said[-1] == _t("owner.channel_unreadable")
    assert telegram.built == [], "nothing to check, so nothing was asked of Telegram"
    assert await owner.state() == ShopOnboarding.waiting_channel.state


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ({"channel": CHAT_NOT_FOUND}, "owner.channel_not_found"),
        ({"channel_member": ok(member(SHOP_BOT_ID, "member"))}, "owner.channel_not_admin"),
        ({"channel": ok(chat(CHANNEL, "supergroup"))}, "owner.channel_wrong_type"),
        ({"channel": error(502, "Bad Gateway")}, "owner.telegram_unreachable"),
    ],
)
async def test_a_channel_the_shop_bot_cannot_work_in_says_why_and_waits(
    owner: Owner,
    telegram: ShopTelegram,
    db: AsyncConnection,
    setup: dict[str, Reply],
    expected: str,
) -> None:
    before = await _shops(db)
    for attr, reply in setup.items():
        setattr(telegram, attr, reply)

    await owner.through_channel()

    assert owner.said[-1] == _t(expected)
    assert await owner.state() == ShopOnboarding.waiting_channel.state
    assert "channel_id" not in await owner.data()
    assert await _shops(db) == before


async def test_after_fixing_the_channel_the_owner_simply_tries_again(
    owner: Owner, telegram: ShopTelegram
) -> None:
    telegram.channel_member = ok(member(SHOP_BOT_ID, "member"))
    await owner.through_channel()
    telegram.channel_member = ok(member(SHOP_BOT_ID, "administrator"))

    await owner.say("@lola")

    assert (await owner.data())["channel_id"] == CHANNEL
    assert await owner.state() == ShopOnboarding.waiting_group.state


async def test_a_token_telegram_rejects_sends_the_owner_back_to_the_token_step(
    owner: Owner, telegram: ShopTelegram, db: AsyncConnection, storage: MemoryStorage
) -> None:
    before = await _shops(db)
    telegram.channel = UNAUTHORIZED

    await owner.through_channel()

    assert owner.said[-1] == _t("owner.token_rejected")
    assert await owner.state() == ShopOnboarding.entering_token.state
    assert "token" not in await owner.data(), "a token Telegram rejected is not kept"
    assert await _shops(db) == before
    _no_plaintext_in(storage)


# --- step 5: the admin group ----------------------------------------------


async def test_the_group_is_picked_with_telegram_s_own_chat_picker(owner: Owner) -> None:
    await owner.through_channel()
    markup = owner.last_markup()
    assert isinstance(markup, ReplyKeyboardMarkup)
    picker = markup.keyboard[0][0].request_chat
    assert picker is not None
    assert (picker.request_id, picker.chat_is_channel) == (GROUP_REQUEST_ID, False)


async def test_the_group_is_checked_by_the_shop_s_bot_including_a_real_post(
    owner: Owner, telegram: ShopTelegram
) -> None:
    await owner.through_group()

    posted = [c for c in telegram.calls() if isinstance(c, SendMessage)]
    assert [p.chat_id for p in posted] == [GROUP]
    assert posted[0].text == _t("owner.group_test_message")
    assert (await owner.data())["group_chat_id"] == GROUP
    assert await owner.state() == ShopOnboarding.sharing_phone.state


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ({"group": CHAT_NOT_FOUND}, "owner.group_not_found"),
        ({"group_member": ok(member(SHOP_BOT_ID, "member"))}, "owner.group_not_admin"),
        ({"group_post": error(403, "Forbidden: not enough rights")}, "owner.group_cannot_post"),
        ({"group": ok(chat(GROUP, "channel"))}, "owner.group_wrong_type"),
    ],
)
async def test_a_group_the_shop_bot_cannot_work_in_says_why_and_waits(
    owner: Owner,
    telegram: ShopTelegram,
    db: AsyncConnection,
    setup: dict[str, Reply],
    expected: str,
) -> None:
    before = await _shops(db)
    for attr, reply in setup.items():
        setattr(telegram, attr, reply)

    await owner.through_group()

    assert owner.said[-1] == _t(expected)
    assert await owner.state() == ShopOnboarding.waiting_group.state
    assert "group_chat_id" not in await owner.data()
    assert await _shops(db) == before


# --- step 6 and the finish: the shop, whole and usable ----------------------


async def test_the_whole_flow_creates_one_complete_usable_shop(
    owner: Owner, db: AsyncConnection, storage: MemoryStorage, created: list[int]
) -> None:
    before = await _shops(db)
    await owner.all_the_way()

    (shop,) = [s for s in await _shops(db) if s not in before]
    assert shop["name"] == "Lola Gullari"
    assert (shop["channel_id"], shop["group_chat_id"]) == (CHANNEL, GROUP)
    assert shop["owner_telegram_ids"] == [OWNER]
    assert (shop["owner_phone"], shop["owner_phone_verified"]) == ("+998901112233", True)
    assert shop["uses_process_bot_token"] is False, "only the pilot keeps the fallback"
    assert shop["bot_telegram_id"] == SHOP_BOT_ID
    assert shop["lang"] == "uz", "an owner with no Russian Telegram gets the default"
    assert SHOP_SECRET not in shop["bot_token_encrypted"]
    assert decrypt_token(shop["bot_token_encrypted"]) == SHOP_TOKEN

    assert owner.said[-1] == _t("owner.done", name="Lola Gullari")
    assert await owner.state() is None
    assert await owner.data() == {}
    assert created == [shop["id"]], "the pollers are told, so the shop goes live now"
    _no_plaintext_in(storage)


async def test_a_russian_speaking_owner_s_shop_is_stored_russian(
    owner: Owner, db: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's language, already derived for the conversation, becomes the
    shop's: what its group, alerts and summary are written in."""

    async def russian(self: Any, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        data["lang"] = "ru"
        return await handler(event, data)

    monkeypatch.setattr(OwnerLanguageMiddleware, "__call__", russian)
    before = await _shops(db)
    await owner.all_the_way()
    (shop,) = [s for s in await _shops(db) if s not in before]
    assert shop["lang"] == "ru"


async def test_a_typed_owner_number_is_stored_unverified(owner: Owner, db: AsyncConnection) -> None:
    await owner.through_group()
    await owner.say("90 111 22 33")
    (shop,) = [s for s in await _shops(db) if s["name"] == "Lola Gullari"]
    assert (shop["owner_phone"], shop["owner_phone_verified"]) == ("+998901112233", False)


async def test_someone_else_s_contact_is_refused(owner: Owner, db: AsyncConnection) -> None:
    await owner.through_group()
    await owner.share_contact(own=False)
    assert owner.said[-1] == _t("phone.not_yours")
    assert await owner.state() == ShopOnboarding.sharing_phone.state
    assert not [s for s in await _shops(db) if s["name"] == "Lola Gullari"]


async def test_a_bot_taken_while_the_owner_was_mid_flow_leaves_no_second_shop(
    owner: Owner, db: AsyncConnection, created: list[int]
) -> None:
    """The last-moment race: another shop registered this bot after the token
    step passed. The final write refuses in the database, the transaction
    rolls back whole, and the owner is sent back for a different bot."""
    await owner.through_group()
    racer = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('Racer', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    async with bound_session_factory(db)() as session:
        await set_shop_bot_token(session, shop_id=racer, token=SHOP_TOKEN)
        await session.commit()

    await owner.share_contact()

    assert owner.said[-1] == _t("owner.token_taken")
    assert [s["name"] for s in await _shops(db)] == ["Racer"]
    assert created == []
    assert await owner.state() == ShopOnboarding.entering_token.state


# --- dropping off, cancelling, coming back ----------------------------------


async def test_cancel_mid_flow_leaves_nothing_behind(
    owner: Owner, db: AsyncConnection, storage: MemoryStorage
) -> None:
    before = await _shops(db)
    await owner.through_channel()
    await owner.say(CANCEL)

    assert owner.said[-1] == _t("owner.cancelled")
    assert await owner.state() is None
    assert await owner.data() == {}
    assert await _shops(db) == before


async def test_start_mid_flow_resumes_at_the_step_the_owner_left(owner: Owner) -> None:
    await owner.through_name()
    await owner.say("/start")

    assert owner.said[-2:] == [_t("owner.resume"), _t("owner.channel_ask")]
    assert await owner.state() == ShopOnboarding.waiting_channel.state
    assert (await owner.data())["name"] == "Lola Gullari"


async def test_a_resumed_branding_question_still_takes_its_buttons(owner: Owner) -> None:
    await owner.through_token()
    await owner.say("/start")
    await owner.tap(OnboardBrandingCB(answer="no").pack())
    assert await owner.state() == ShopOnboarding.entering_shop_name.state


async def test_a_flow_survives_a_restart_and_finishes_from_where_it_was(
    db: AsyncConnection,
    key: str,
    process_token: None,
    storage: MemoryStorage,
    telegram: ShopTelegram,
    created: list[int],
) -> None:
    """Dropped off at the group step; the bot process restarted since. The
    state lives in storage, not in the process, so /start picks it up."""
    first = _platform(db, storage, telegram, created)
    await first.through_channel()

    again = _platform(db, storage, telegram, created)  # a new process
    again._update = first._update
    await again.say("/start")
    assert again.said == [_t("owner.resume"), _t("owner.group_ask")]
    await again.share_group(GROUP)
    await again.share_contact()

    assert [s["name"] for s in await _shops(db)] == ["Lola Gullari"]
    assert len(created) == 1


async def test_a_finished_owner_can_start_a_second_shop(owner: Owner) -> None:
    await owner.all_the_way()
    await owner.say("/start")
    assert owner.said[-1] == _t("owner.welcome")


# --- the platform bot's own boundaries -------------------------------------


async def test_the_platform_bot_ignores_groups(owner: Owner) -> None:
    update = text_update("/start", user_id=OWNER, update_id=900)
    assert update.message is not None
    grouped = update.model_copy(
        update={
            "message": update.message.model_copy(
                update={"chat": Chat(id=-1_009_999, type="supergroup", title="G")}
            )
        }
    )
    await owner.send(grouped)
    assert owner.said == []


async def test_the_platform_bot_never_registers_anyone_as_a_customer(
    owner: Owner, db: AsyncConnection
) -> None:
    await owner.all_the_way()
    customers = (
        await db.execute(
            text("SELECT count(*) FROM customers WHERE telegram_user_id = :u"), {"u": OWNER}
        )
    ).scalar_one()
    assert customers == 0


async def test_fsm_keys_for_the_platform_are_its_own(owner: Owner, storage: MemoryStorage) -> None:
    await owner.through_token()
    keys = list(storage.storage)
    assert keys and all(isinstance(k, StorageKey) and k.bot_id == 999999 for k in keys)


# --- the hand-off: a finished onboarding puts the new shop's bot live -------


async def test_a_new_shop_is_polled_the_moment_onboarding_finishes(
    db: AsyncConnection,
    key: str,
    process_token: None,
    storage: MemoryStorage,
    telegram: ShopTelegram,
) -> None:
    """The platform dispatcher wired to the real ShopPollers, as run.py wires
    them: the owner's last answer is what starts the shop's long-poll, with no
    restart and no wait for the periodic refresh."""
    import asyncio

    from gulbot.bot.run import ShopPollers

    polled: list[str] = []

    async def poll(dispatcher: Dispatcher, bot: Bot) -> None:
        polled.append(bot.token)
        await asyncio.Event().wait()

    pollers = ShopPollers(
        bound_session_factory(db), storage=MemoryStorage(), bot_factory=telegram.factory, poll=poll
    )

    async def start_new_shop(shop_id: int) -> None:
        await pollers.sync()

    dispatcher = build_platform_dispatcher(
        session_factory=bound_session_factory(db),
        storage=storage,
        shop_bot_factory=telegram.factory,
        on_shop_created=start_new_shop,
    )
    recorder = RecordingSession()
    owner = Owner(dispatcher, Bot(token=PLATFORM_TOKEN, session=recorder), recorder)
    try:
        await owner.all_the_way()
        await asyncio.sleep(0)
        (shop,) = [s for s in await _shops(db) if s["name"] == "Lola Gullari"]
        assert list(pollers.running) == [shop["id"]]
        assert pollers.running[shop["id"]].bot.token == SHOP_TOKEN
        assert polled == [SHOP_TOKEN]
    finally:
        await pollers.stop()
