"""L2 of AUDIT_MULTI_TENANT.md: what a shop's own people read follows the shop.

THE FINDING. Everything the SHOP reads -- the order card in its group, the
delivery pings, the stall and dead-letter alerts, the daily summary, the
stamped outcome when an admin taps Confirm -- was in Uzbek by construction:
`lang: str = "uz"` defaults that no caller ever overrode, and the admin group
given `DEFAULT_LANGUAGE`. A fleet spanning more than one language had nowhere
to say otherwise.

WHAT CP-MT2 DOES, AND WHAT IT CANNOT. The place to record a shop's language is
a `shops.lang` column, and that is a migration -- deliberately not part of this
branch (see CHECKPOINTS.md, CP-MT2, for the plan). Everything else is done:
every shop-facing path now asks ONE function, `shop_language(session,
shop_id=...)`, per shop, and nothing shop-facing names a language itself. Until
the column exists that function answers DEFAULT_LANGUAGE for every shop; the
migration changes that one function and nothing else.

HOW IT IS PROVEN WITHOUT THE COLUMN. The function is replaced, per module, by
one that answers Russian for shop B only. Each path must then speak Russian to
B and Uzbek to A in the same run -- which fails for any path that resolved the
language once, for the wrong shop, or not at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from aiogram.types import Chat
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.test_order_pings import _make_order, _ping

import gulbot.bot.middlewares as middlewares
import gulbot.sending.alerts as alerts
import gulbot.sending.order_pings as order_pings
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.order_card import ANNOUNCEMENT
from gulbot.sending.transport import SendResult

pytestmark = pytest.mark.infra

GROUP = {"A": -1_001_111, "B": -1_002_222}
NOW = datetime(2027, 3, 8, 16, 0, tzinfo=UTC)


class Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_text(self, *, chat_id: int, text: str, reply_markup: Any = None) -> SendResult:
        self.sent.append((chat_id, text))
        return SendResult.sent(len(self.sent))

    async def send_photo(
        self, *, chat_id: int, file_id: str, caption: str, reply_markup: Any = None
    ) -> SendResult:
        self.sent.append((chat_id, caption))
        return SendResult.sent(len(self.sent))


@pytest_asyncio.fixture
async def shops(db: AsyncConnection, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    out: dict[str, int] = {}
    for label in ("A", "B"):
        out[label] = (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours, group_chat_id) "
                    "VALUES (:n, CAST(:wh AS jsonb), :g) RETURNING id"
                ),
                {"n": label, "wh": json.dumps(DEFAULT_WORKING_HOURS), "g": GROUP[label]},
            )
        ).scalar_one()

    async def russian_for_b(session: Any, *, shop_id: int) -> str:
        return "ru" if shop_id == out["B"] else "uz"

    # raising=False: before the fix these modules had no such name, and the
    # test must then fail on what was SENT, not on the patch.
    for module in (alerts, order_pings, middlewares):
        monkeypatch.setattr(module, "shop_language", russian_for_b, raising=False)
    return out


def _by_group(sent: list[tuple[int, str]]) -> dict[str, str]:
    by_chat = dict(sent)
    return {label: by_chat.get(chat, "") for label, chat in GROUP.items()}


async def test_the_daily_summary_is_in_each_shops_language(
    db: AsyncConnection, shops: dict[str, int]
) -> None:
    transport = Recorder()
    async with bound_session_factory(db)() as session:
        await alerts.announce_for_every_shop(
            session, job="summary", transport_for=lambda shop_id: transport, now_utc=NOW
        )
    text_ = _by_group(transport.sent)
    assert "Bugun" in text_["A"]
    assert "Сегодня" in text_["B"], "shop B was told in the default language"


async def test_a_stall_alert_is_in_each_shops_language(
    db: AsyncConnection, shops: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    for label in ("A", "B"):
        customer = (
            await db.execute(
                text(
                    "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"
                ),
                {"s": shops[label], "t": 4_000 + len(label)},
            )
        ).scalar_one()
        order = await _make_order(db, shops[label], customer, token=f"stall-{label}")
        await _ping(db, shops[label], order, due=NOW - timedelta(hours=2))

    class AlwaysClaim:
        async def claim(self, *, shop_id: int, kind: str) -> bool:
            return True

    class NoCooldown:
        async def __aenter__(self) -> AlwaysClaim:
            return AlwaysClaim()

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(alerts, "alert_cooldown", NoCooldown)
    transport = Recorder()
    async with bound_session_factory(db)() as session:
        await alerts.announce_for_every_shop(
            session, job="check", transport_for=lambda shop_id: transport, now_utc=NOW
        )
    text_ = _by_group(transport.sent)
    assert "Diqqat" in text_["A"]
    assert "Внимание" in text_["B"]


async def test_order_cards_in_one_tick_are_each_in_their_shops_language(
    db: AsyncConnection, shops: dict[str, int]
) -> None:
    """One tick, both shops: a language resolved once per tick would give
    both the same."""
    for label in ("A", "B"):
        customer = (
            await db.execute(
                text(
                    "INSERT INTO customers (shop_id, telegram_user_id, phone, phone_verified) "
                    "VALUES (:s, :t, '+998901234567', true) RETURNING id"
                ),
                {"s": shops[label], "t": 4_100 + len(label)},
            )
        ).scalar_one()
        order = await _make_order(db, shops[label], customer, token=f"card-{label}")
        await _ping(db, shops[label], order, number=ANNOUNCEMENT)

    transport = Recorder()
    async with bound_session_factory(db)() as session:
        await order_pings.run_order_ping_tick(
            session,
            transport=transport,  # type: ignore[arg-type]
            now_utc=datetime.now(UTC),
        )
    text_ = _by_group(transport.sent)
    assert "Yangi buyurtma" in text_["A"]
    assert "Новый заказ" in text_["B"]


async def test_the_admin_group_is_spoken_to_in_its_shops_language(
    db: AsyncConnection, shops: dict[str, int]
) -> None:
    """The group's buttons and stamped outcomes are rendered in `data["lang"]`,
    which the customer middleware sets for a group from the shop."""
    seen: dict[str, Any] = {}

    async def handler(event: Any, data: dict[str, Any]) -> None:
        seen.update(data)

    async with bound_session_factory(db)() as session:
        gate = middlewares.CustomerMiddleware(shops["B"])
        await gate(
            handler,
            object(),  # type: ignore[arg-type]
            {
                "event_chat": Chat(id=GROUP["B"], type="supergroup"),
                "event_from_user": None,
                "session": session,
            },
        )
    assert seen["lang"] == "ru"


# --- the stored language: shops.lang (the CP-MT2 follow-up) ---------------------


async def test_the_stored_language_is_what_each_shop_reads(db: AsyncConnection) -> None:
    """No replacement here: shop B is STORED as Russian, and shop_language reads
    it per shop. Before the column existed every shop read the default."""
    from gulbot.services.shop_language import shop_language

    ids: dict[str, int] = {}
    for label in ("A", "B"):
        ids[label] = (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours) "
                    "VALUES (:n, CAST(:wh AS jsonb)) RETURNING id"
                ),
                {"n": f"lang-{label}", "wh": json.dumps(DEFAULT_WORKING_HOURS)},
            )
        ).scalar_one()
    await db.execute(text("UPDATE shops SET lang = 'ru' WHERE id = :b"), {"b": ids["B"]})
    async with bound_session_factory(db)() as session:
        read = {label: await shop_language(session, shop_id=ids[label]) for label in ids}
    assert read == {"A": "uz", "B": "ru"}


async def test_a_shop_language_outside_the_known_set_is_refused(db: AsyncConnection) -> None:
    """The same CHECK as customers.lang: one definition of a language code."""
    try:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours, lang) "
                    "VALUES ('lang-x', CAST(:wh AS jsonb), 'de')"
                ),
                {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
            )
    except Exception as error:  # noqa: BLE001 - the constraint's name is the assertion
        refused = str(error)
    else:
        refused = ""
    assert "ck_shops_lang_known" in refused, refused or "a 'de' shop was accepted"
