"""CP9: a reminder carries a bouquet, and never loses a reminder to do it.

Two levels, and the split is deliberate:

* `choose_bouquet` is the ranking rule and the exclusions -- tested directly,
  because "which product" is a question with an exact answer;
* `run_tick` with an attacher is the delivery contract -- tested through the
  real dispatcher, because the thing that matters there is that a group is
  still ONE call and still marked in one update.

THE RULE THAT OUTRANKS EVERY OTHER TEST HERE: the catalogue may ADD to a
reminder, it may never COST one. Every failure mode -- empty catalogue, no
match, a caption too long -- falls back to the bare text CP6 sent.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import bound_session_factory

from gulbot.models.notification import NotificationState
from gulbot.models.recipient import FLOWER_PRESETS
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.attach import attach_bouquet, leading_recipient
from gulbot.sending.dispatcher import run_tick
from gulbot.sending.render import render_reminder
from gulbot.sending.transport import CAPTION_LIMIT, SendResult
from gulbot.services.bouquets import choose_bouquet

pytestmark = pytest.mark.infra

NOW = datetime(2027, 3, 7, 6, 0, tzinfo=UTC)


class RecordingTransport:
    """Records which capability was used, not just what was said."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.photos: list[tuple[str, str]] = []
        self.markups: list[object] = []

    async def send_text(self, *, chat_id: int, text: str) -> SendResult:
        self.texts.append(text)
        return SendResult.sent(len(self.texts) + len(self.photos))

    async def send_photo(
        self, *, chat_id: int, file_id: str, caption: str, reply_markup: object = None
    ) -> SendResult:
        # CP10 added the order button; recorded so the flow tests can assert
        # a bouquet is actually orderable.
        self.markups.append(reply_markup)
        self.photos.append((file_id, caption))
        return SendResult.sent(len(self.texts) + len(self.photos))

    @property
    def calls(self) -> int:
        return len(self.texts) + len(self.photos)


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('S', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 9901) RETURNING id"
            ),
            {"s": shop},
        )
    ).scalar_one()
    return {"db": db, "shop": shop, "customer": customer, "sessions": bound_session_factory(db)}


async def add_recipient(
    world: dict, *, label: str, preferred: str | None = None, rtype: str = "mother"
) -> int:
    return (
        await world["db"].execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type, preferred_hashtag) "
                "VALUES (:s, :c, :l, :t, :p) RETURNING id"
            ),
            {"s": world["shop"], "c": world["customer"], "l": label, "p": preferred, "t": rtype},
        )
    ).scalar_one()


async def add_product(
    world: dict,
    *,
    name: str,
    tags: tuple[str, ...] = (),
    price: int | None = None,
    confidence: str = "none",
    finalized: bool = True,
    active: bool = True,
    deleted: bool = False,
    indexed_offset: int = 0,
    message_id: int = 1,
) -> int:
    product = (
        await world["db"].execute(
            text(
                "INSERT INTO products (shop_id, name, telegram_file_id, source, "
                " channel_message_id, channel_chat_id, price_uzs, price_confidence, "
                " indexed_at, finalized_at, active, deleted_at) "
                "VALUES (:s, :n, :f, 'channel', :mid, -100, :p, :pc, "
                " now() + make_interval(secs => :off), "
                " CASE WHEN :fin THEN now() ELSE NULL END, :act, "
                " CASE WHEN :del THEN now() ELSE NULL END) RETURNING id"
            ),
            {
                "s": world["shop"],
                "n": name,
                "f": f"file-{name}",
                "mid": message_id,
                "p": price,
                "pc": confidence,
                "off": indexed_offset,
                "fin": finalized,
                "act": active,
                "del": deleted,
            },
        )
    ).scalar_one()
    for tag in tags:
        await world["db"].execute(
            text(
                "INSERT INTO product_hashtags (shop_id, product_id, hashtag_normalized) "
                "VALUES (:s, :p, :t)"
            ),
            {"s": world["shop"], "p": product, "t": tag},
        )
    return product


async def add_due_row(
    world: dict, *, recipient: int, day: int, offset: int, merge_key: str | None = None
) -> None:
    occasion = (
        await world["db"].execute(
            text(
                "INSERT INTO occasions "
                "(shop_id, customer_id, recipient_id, label, type, kind, month, day) "
                "VALUES (:s, :c, :r, 'X', 'mother', 'birthday', 3, :d) RETURNING id"
            ),
            {"s": world["shop"], "c": world["customer"], "r": recipient, "d": day},
        )
    ).scalar_one()
    await world["db"].execute(
        text(
            "INSERT INTO scheduled_notifications "
            "(shop_id, customer_id, occasion_id, occurrence_year, offset_days, due_at_utc, "
            " channel, merge_key) "
            "VALUES (:s, :c, :o, 2027, :off, :due, 'telegram', :mk)"
        ),
        {
            "s": world["shop"],
            "c": world["customer"],
            "o": occasion,
            "off": offset,
            "due": NOW - timedelta(minutes=1),
            "mk": merge_key,
        },
    )


async def tick(
    world: dict, *, with_bouquets: bool = True, render: Any = render_reminder
) -> tuple[Any, RecordingTransport]:
    transport = RecordingTransport()
    sessions: async_sessionmaker[AsyncSession] = world["sessions"]
    async with sessions() as session:

        async def attach(group):  # type: ignore[no-untyped-def]
            return await attach_bouquet(session, group, render=render)

        result = await run_tick(
            session,
            transport=transport,
            render=render,
            now_utc=NOW,
            attach=attach if with_bouquets else None,
        )
        await session.commit()
    return result, transport


# --- the ranking rule ------------------------------------------------------


async def test_the_preferred_hashtag_wins_over_recency(world: dict) -> None:
    """The whole ranking rule in one test: preference first, recency second."""
    await add_product(world, name="tulip", tags=("tyulpan",), indexed_offset=0, message_id=1)
    await add_product(world, name="newer-rose", tags=("atirgul",), indexed_offset=60, message_id=2)

    async with world["sessions"]() as session:
        chosen = await choose_bouquet(session, shop_id=world["shop"], preferred_hashtag="tyulpan")

    assert chosen is not None
    assert chosen.name == "tulip", "recency beat the stated preference"


async def test_with_no_preference_the_newest_wins(world: dict) -> None:
    await add_product(world, name="older", indexed_offset=0, message_id=1)
    await add_product(world, name="newer", indexed_offset=60, message_id=2)

    async with world["sessions"]() as session:
        chosen = await choose_bouquet(session, shop_id=world["shop"])

    assert chosen is not None and chosen.name == "newer"


async def test_an_unmatched_preference_still_returns_something(world: dict) -> None:
    """A preference is a HINT. A customer who likes tulips still gets a
    reminder with a rose rather than no bouquet at all."""
    await add_product(world, name="rose", tags=("atirgul",), message_id=1)

    async with world["sessions"]() as session:
        chosen = await choose_bouquet(session, shop_id=world["shop"], preferred_hashtag="tyulpan")

    assert chosen is not None and chosen.name == "rose"


async def add_alias(world: dict, alias: str, canonical: str) -> None:
    await world["db"].execute(
        text(
            "INSERT INTO hashtag_aliases (shop_id, alias_normalized, canonical_hashtag) "
            "VALUES (:s, :a, :c)"
        ),
        {"s": world["shop"], "a": alias, "c": canonical},
    )


async def test_a_shop_using_its_own_word_for_roses_still_matches_the_preset(
    world: dict,
) -> None:
    """CP9.5, and the case CP9 got backwards.

    A real shop tags its roses with its own word. The customer's preset is
    `atirgul`, because `preferred_hashtag` is CHECK-constrained to the three
    presets. CP9 compared those two strings directly, so the preference tier
    could only fire for a shop whose vocabulary already happened to be ours --
    and in the live catalogue it never fired at all.

    The fix resolves the STORED tag forward instead. One alias row closes the
    gap, with no change to the CHECK or to the preference buttons.
    """
    await add_product(world, name="shop-roses", tags=("gulkinder",), indexed_offset=0, message_id=1)
    await add_product(
        world, name="unrelated-newer", tags=("boshqa",), indexed_offset=60, message_id=2
    )
    await add_alias(world, "gulkinder", "atirgul")

    async with world["sessions"]() as session:
        chosen = await choose_bouquet(session, shop_id=world["shop"], preferred_hashtag="atirgul")

    assert chosen is not None
    assert chosen.name == "shop-roses", "the stored tag was not resolved through the alias table"


async def test_a_seeded_synonym_matches_the_preset_too(world: dict) -> None:
    """The same bug, without any custom vocabulary at all.

    `roza -> atirgul` is in the shipped fixture. A shop tagging `#roza` -- an
    ordinary spelling, nothing exotic -- was equally invisible to a customer
    who prefers `atirgul`. This is why CP9.5 is a correctness fix and not a
    convenience for unusual shops.
    """
    await add_product(world, name="roza-roses", tags=("roza",), indexed_offset=0, message_id=1)
    await add_product(world, name="newer-other", tags=("boshqa",), indexed_offset=60, message_id=2)
    await add_alias(world, "roza", "atirgul")

    async with world["sessions"]() as session:
        chosen = await choose_bouquet(session, shop_id=world["shop"], preferred_hashtag="atirgul")

    assert chosen is not None and chosen.name == "roza-roses"


async def test_a_product_tagged_with_the_preset_itself_still_matches(world: dict) -> None:
    """Regression guard. Resolving the stored side must not break the plain
    case where the shop already uses our word and there is no alias row."""
    await add_product(world, name="plain", tags=("atirgul",), indexed_offset=0, message_id=1)
    await add_product(world, name="newer-other", tags=("boshqa",), indexed_offset=60, message_id=2)

    async with world["sessions"]() as session:
        chosen = await choose_bouquet(session, shop_id=world["shop"], preferred_hashtag="atirgul")

    assert chosen is not None and chosen.name == "plain"


async def test_an_unaliased_shop_word_does_not_match(world: dict) -> None:
    """Guards the guard. Without an alias row `gulkinder` means nothing to us,
    and inventing a match would be exactly the false positive that ruled out
    fuzzy search in the first place."""
    await add_product(world, name="shop-roses", tags=("gulkinder",), indexed_offset=0, message_id=1)
    await add_product(world, name="newer-other", tags=("boshqa",), indexed_offset=60, message_id=2)

    async with world["sessions"]() as session:
        chosen = await choose_bouquet(session, shop_id=world["shop"], preferred_hashtag="atirgul")

    assert chosen is not None and chosen.name == "newer-other", "an unaliased word matched"


async def test_one_of_several_tags_resolving_is_enough(world: dict) -> None:
    """A post carries several hashtags. The match is EXISTS over them, which is
    also why a join would be wrong -- it would return the product once per tag."""
    await add_product(
        world, name="multi", tags=("katta", "gulkinder", "sovga"), indexed_offset=0, message_id=1
    )
    await add_product(world, name="newer-other", tags=("boshqa",), indexed_offset=60, message_id=2)
    await add_alias(world, "gulkinder", "atirgul")

    async with world["sessions"]() as session:
        chosen = await choose_bouquet(session, shop_id=world["shop"], preferred_hashtag="atirgul")

    assert chosen is not None and chosen.name == "multi"


def test_the_preference_tests_only_use_storable_presets() -> None:
    """Pins the mistake CP9's alias test made.

    That test passed an ALIAS (roza) as the preference straight to
    `choose_bouquet`, bypassing the CHECK -- so it asserted a scenario
    production can never produce, and went on passing while the real direction
    was broken. Every preference used in this file must be a value the database
    would actually accept.

    The offending literal is deliberately not spelled out above: this test scans
    its own source, and quoting the mistake verbatim would make it flag itself.
    """
    import re

    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    used = set(re.findall(r'preferred_hashtag="([a-z]+)"', source))
    used |= set(re.findall(r'preferred="([a-z]+)"', source))
    assert used, "guards the guard: no preferences found to check"
    assert used <= set(FLOWER_PRESETS), (
        f"these are not storable in recipients.preferred_hashtag: "
        f"{sorted(used - set(FLOWER_PRESETS))}"
    )


# --- the exclusions --------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"finalized": False}, "a provisional album has no settled name, price or tags"),
        ({"active": False}, "the shop hid it"),
        ({"deleted": True}, "it is gone from the channel"),
    ],
)
async def test_excluded_products_are_never_chosen(world: dict, kwargs: dict, why: str) -> None:
    await add_product(world, name="hidden", tags=("atirgul",), message_id=1, **kwargs)

    async with world["sessions"]() as session:
        assert await choose_bouquet(session, shop_id=world["shop"]) is None, why


async def test_an_excluded_product_does_not_hide_a_good_one(world: dict) -> None:
    """Guards the guard: the filter must exclude the bad row, not every row."""
    await add_product(world, name="provisional", finalized=False, indexed_offset=60, message_id=1)
    await add_product(world, name="good", indexed_offset=0, message_id=2)

    async with world["sessions"]() as session:
        chosen = await choose_bouquet(session, shop_id=world["shop"])

    assert chosen is not None and chosen.name == "good"


async def test_another_shops_product_is_never_chosen(world: dict) -> None:
    other = (
        await world["db"].execute(
            text("INSERT INTO shops (name, working_hours) VALUES ('other', '{}') RETURNING id")
        )
    ).scalar_one()
    await world["db"].execute(
        text(
            "INSERT INTO products (shop_id, name, telegram_file_id, source, channel_message_id, "
            " finalized_at) VALUES (:s, 'theirs', 'f', 'channel', 1, now())"
        ),
        {"s": other},
    )

    async with world["sessions"]() as session:
        assert await choose_bouquet(session, shop_id=world["shop"]) is None


# --- delivery: the reminder must never be lost -----------------------------


async def test_a_reminder_with_a_bouquet_is_one_photo_call(world: dict) -> None:
    recipient = await add_recipient(world, label="Onam", preferred="atirgul")
    await add_product(
        world,
        name="Qizil atirgul",
        tags=("atirgul",),
        price=450000,
        confidence="high",
        message_id=1,
    )
    await add_due_row(world, recipient=recipient, day=8, offset=-1)

    result, transport = await tick(world)

    assert result.sent == 1
    assert transport.calls == 1, "a bouquet must not cost a second API call"
    assert transport.texts == []
    file_id, caption = transport.photos[0]
    assert file_id == "file-Qizil atirgul"
    assert "450 000" in caption
    assert "Onangiz" in caption, "the reminder itself must still be in the caption"


async def test_an_empty_catalogue_still_sends_the_reminder(world: dict) -> None:
    """The rule that outranks everything else in this file."""
    recipient = await add_recipient(world, label="Onam")
    await add_due_row(world, recipient=recipient, day=8, offset=-1)

    result, transport = await tick(world)

    assert result.sent == 1
    assert transport.calls == 1
    assert len(transport.texts) == 1 and transport.photos == []

    states = (
        (
            await world["db"].execute(
                text("SELECT state FROM scheduled_notifications WHERE shop_id = :s"),
                {"s": world["shop"]},
            )
        )
        .scalars()
        .all()
    )
    assert list(states) == [NotificationState.SENT.value]


async def test_an_unpriced_bouquet_is_shown_with_the_operator_line(world: dict) -> None:
    """A named requirement since the original brief: never drop an unpriced post."""
    recipient = await add_recipient(world, label="Onam")
    await add_product(world, name="Lola buketi", tags=("lola",), message_id=1)
    await add_due_row(world, recipient=recipient, day=8, offset=-1)

    _, transport = await tick(world)

    _, caption = transport.photos[0]
    assert "Lola buketi" in caption
    assert "narx operator tomonidan tasdiqlanadi" in caption


async def test_a_merged_group_gets_one_reminder_and_one_bouquet(world: dict) -> None:
    onam = await add_recipient(world, label="Onam", preferred="atirgul")
    opa = await add_recipient(world, label="Opa", preferred="lola", rtype="older_sister")
    await add_product(world, name="rose", tags=("atirgul",), message_id=1)
    await add_product(world, name="lily", tags=("lola",), indexed_offset=60, message_id=2)
    await add_due_row(world, recipient=onam, day=8, offset=-1, merge_key="cluster")
    await add_due_row(world, recipient=opa, day=10, offset=-3, merge_key="cluster")

    result, transport = await tick(world)

    assert result.sent == 1
    assert transport.calls == 1, "a merged group is still one message"
    file_id, caption = transport.photos[0]
    assert "Onangiz" in caption and "Opangiz" in caption
    assert file_id == "file-rose", "the bouquet must follow the SOONEST occasion's recipient"


async def test_a_caption_too_long_falls_back_to_text(world: dict) -> None:
    """Rather than truncating a reminder or splitting it into two sends.

    Driven through the RENDERER rather than a giant product name, because
    `products.name` is String(200) and could never reach the limit on its own --
    a merged reminder for many occasions can.
    """
    recipient = await add_recipient(world, label="Onam")
    await add_product(world, name="rose", tags=("atirgul",), message_id=1)
    await add_due_row(world, recipient=recipient, day=8, offset=-1)

    result, transport = await tick(world, render=lambda group: "x" * (CAPTION_LIMIT - 10))

    assert result.sent == 1
    assert transport.calls == 1
    assert len(transport.texts) == 1 and transport.photos == [], (
        "the bouquet line pushed the caption over the limit; the reminder must still go"
    )


async def test_a_caption_that_just_fits_still_carries_the_bouquet(world: dict) -> None:
    """Guards the guard: the limit must reject only what is actually too long."""
    recipient = await add_recipient(world, label="Onam")
    await add_product(world, name="rose", tags=("atirgul",), message_id=1)
    await add_due_row(world, recipient=recipient, day=8, offset=-1)

    result, transport = await tick(world, render=lambda group: "x" * 100)

    assert result.sent == 1
    assert len(transport.photos) == 1 and transport.texts == []


async def test_without_an_attacher_the_tick_is_exactly_cp6(world: dict) -> None:
    """The compatibility claim, asserted rather than assumed.

    A catalogue full of matching products changes nothing if no attacher is
    passed -- which is why every CP6 dispatcher test still passes unmodified.
    """
    recipient = await add_recipient(world, label="Onam", preferred="atirgul")
    await add_product(world, name="rose", tags=("atirgul",), message_id=1)
    await add_due_row(world, recipient=recipient, day=8, offset=-1)

    result, transport = await tick(world, with_bouquets=False)

    assert result.sent == 1
    assert len(transport.texts) == 1 and transport.photos == []


# --- the merged-group tie-break, on its own --------------------------------


async def test_the_leading_recipient_is_the_soonest_not_the_first_row(world: dict) -> None:
    """Days ahead is -offset_days, so the soonest occasion has the LARGEST
    offset. Getting that backwards would show the bouquet for the person the
    message mentions last."""
    onam = await add_recipient(world, label="Onam", preferred="atirgul")
    opa = await add_recipient(world, label="Opa", preferred="lola", rtype="older_sister")
    await add_due_row(world, recipient=opa, day=10, offset=-3, merge_key="cluster")
    await add_due_row(world, recipient=onam, day=8, offset=-1, merge_key="cluster")

    from gulbot.sending.dispatcher import group_due_rows, select_due_rows

    async with world["sessions"]() as session:
        rows = await select_due_rows(session, now_utc=NOW, limit=10)
        from gulbot.sending.dispatcher import _load_group_context

        occasions, recipients, customers = await _load_group_context(session, rows)
        groups = group_due_rows(rows, occasions, recipients, customers)

    assert len(groups) == 1
    leader = leading_recipient(groups[0])
    assert leader is not None and leader.label == "Onam"
