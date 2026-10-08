"""Uzrnoma, the apology letter (CP17): the third page type.

The creator writes the letter; the recipient presses "Kechirdim", while
"Hali o'ylab ko'raman" runs away with gentle, never-repeating lines; the
creator hears the answer exactly once; the page locks once answered.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import RecordingSession, bound_session_factory
from tests.share_pages_harness import ShopBot
from tests.test_share_pages_service import make_customer, make_shop

from gulbot.bot.callbacks import (
    EditFieldCB,
    MyPageCB,
    PageChoiceCB,
    PageConfirmCB,
    PageLangCB,
    PageMenuCB,
    PageTemplateCB,
)
from gulbot.bot.registry import BotRegistry
from gulbot.i18n.catalog import CATALOG
from gulbot.models.share_page import PAGE_LANGUAGES
from gulbot.sending import page_notify
from gulbot.services import share_pages
from gulbot.services.share_pages import ApologyDraft, EditRefused, InvalidDraft
from gulbot.web import strings
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra

JSON_HEADERS = {"Content-Type": "application/json", "X-Requested-With": "gulbot"}
LETTER = "Kecha aytgan so'zlarim uchun uzr. <b>Seni</b> xafa qilmoqchi emasdim."


def draft(**kw: Any) -> ApologyDraft:
    values: dict[str, Any] = {
        "template": "romantik",
        "lang": "uz",
        "text": LETTER,
        "notify_creator": True,
    }
    return ApologyDraft(**(values | kw))


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


async def made(
    session: AsyncSession, db: AsyncConnection, *, user: int = 760, **kw: Any
) -> tuple[Any, int, int]:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, user)
    page = await share_pages.create_page(
        session, shop_id=shop, customer_id=customer, bot_username="lola_bot", draft=draft(**kw)
    )
    return page, shop, customer


# --- the lines -----------------------------------------------------------------------


def test_the_think_button_has_ten_gentle_different_lines_in_every_language() -> None:
    for lang in PAGE_LANGUAGES:
        lines = strings.APOLOGY_LINES[lang]
        escalation = lines[1:]
        assert len(escalation) >= 10, (lang, len(escalation))
        assert len(set(escalation)) == len(escalation), f"{lang} repeats a line"
        assert lines[0] not in escalation
    assert len({len(strings.APOLOGY_LINES[lang]) for lang in PAGE_LANGUAGES}) == 1
    # Uzbek Cyrillic is the Latin lines transliterated, not Latin left behind.
    for line in strings.APOLOGY_LINES["uz_cyrl"]:
        assert not re.search(r"[A-Za-z]", line), line


# --- the service ---------------------------------------------------------------------


async def test_a_letter_is_stored_and_answered_once(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await made(session, db)
    assert page.kind == "apology" and page.message == LETTER and page.question is None
    first = await share_pages.answer_yes(session, page.token)
    again = await share_pages.answer_yes(session, page.token)
    assert first is not None and first.first and first.notify and not first.has_plan
    assert again is not None and not again.first


async def test_an_empty_letter_is_refused(db: AsyncConnection, session: AsyncSession) -> None:
    # Asserted by type: a database CHECK firing behind a missing guard is a
    # failed assertion here, not a pass.
    try:
        await made(session, db, text="   ")
    except Exception as error:  # noqa: BLE001 - the type is the assertion
        refused: BaseException | None = error
    else:
        refused = None
    assert isinstance(refused, InvalidDraft), repr(refused)


async def test_the_database_refuses_a_live_letter_without_its_text(
    db: AsyncConnection, session: AsyncSession
) -> None:
    """The second wall, under the service: `ck_share_pages_apology_complete`.
    The CHECK guard compares quoted literals only, so a migration that made
    this constraint vacuous would pass it -- this asks Postgres directly."""
    page, _, _ = await made(session, db)
    await session.flush()
    try:
        async with db.begin_nested():
            await db.execute(
                text("UPDATE share_pages SET message = NULL WHERE id = :id"), {"id": page.id}
            )
    except Exception as error:  # noqa: BLE001 - the type and name are the assertion
        refused: BaseException | None = error
    else:
        refused = None
    assert refused is not None and "ck_share_pages_apology_complete" in str(refused), repr(refused)


async def test_the_letter_is_editable_until_it_is_forgiven(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db)

    async def edit(**changes: object) -> Any:
        return await share_pages.update_page(
            session, shop_id=shop, customer_id=customer, page_id=page.id, changes=changes
        )

    try:  # the letter IS an editable field -- a refusal here is a failed assertion
        edited: Any = await edit(message="Yangi matn")
    except EditRefused as refused:
        edited = refused
    assert getattr(edited, "message", None) == "Yangi matn", repr(edited)
    with pytest.raises(EditRefused, match="invalid"):
        await edit(question="Not a field of a letter")
    try:  # a letter cannot be emptied -- refused here, not by the database
        await edit(message="  ")
    except Exception as error:  # noqa: BLE001 - the type is the assertion
        emptied: BaseException | None = error
    else:
        emptied = None
    assert isinstance(emptied, EditRefused) and emptied.reason == "invalid", repr(emptied)
    await share_pages.answer_yes(session, page.token)
    with pytest.raises(EditRefused, match="locked"):
        await edit(message="Too late")


# --- the creator's message -----------------------------------------------------------------


class Bots:
    def __init__(self) -> None:
        self.session = RecordingSession()

    def registry(self) -> BotRegistry:
        return BotRegistry(token_for=lambda _shop: "111111:" + "A" * 35, bot_factory=self.bot)

    def bot(self, token: str | None) -> Bot:
        return Bot(token=token or "x", session=self.session)

    def sent(self) -> list[str]:
        return [c.text for c in self.session.calls if isinstance(c, SendMessage)]


@pytest.fixture
def bots(monkeypatch: pytest.MonkeyPatch) -> Bots:
    recorded = Bots()

    async def registry_for(_session: Any, **_kw: Any) -> BotRegistry:
        return recorded.registry()

    monkeypatch.setattr(page_notify, "registry_for", registry_for)
    return recorded


async def test_the_creator_hears_forgiven_exactly_once(
    db: AsyncConnection, session: AsyncSession, bots: Bots
) -> None:
    page, _, _ = await made(session, db)
    await share_pages.answer_yes(session, page.token)
    await session.commit()
    for _ in range(3):
        await page_notify.notify_page_answer(page.id, session_factory=bound_session_factory(db))
    [message] = bots.sent()
    assert message.startswith(CATALOG["pages.notify_forgiven"]["uz"].split("{")[0].rstrip())
    assert "&lt;b&gt;Seni&lt;/b&gt;" in message  # the letter, quoted back escaped


# --- the page --------------------------------------------------------------------------------


def app_for(db: AsyncConnection) -> Any:
    return build_app(
        session_factory=bound_session_factory(db),
        notify=lambda _id, _delay: None,
        public_base_url="http://127.0.0.1:8088",
    )


async def test_the_page_is_a_letter_with_kechirdim_and_a_shy_second_button(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await made(session, db)
    await session.commit()
    async with TestClient(TestServer(app_for(db))) as client:
        html = await (await client.get(f"/p/{page.token}")).text()
        assert '<p class="letter">' in html and "&lt;b&gt;Seni&lt;/b&gt;" in html
        assert ">Kechirdim 🤍</button>" in html
        assert ">Hali o&#39;ylab ko&#39;raman</button>" in html
        lines = json.loads(
            html.split('data-lines="')[1].split('"')[0].replace("&#34;", '"').replace("&#39;", "'")
        )
        assert lines == list(strings.APOLOGY_LINES["uz"])
        # The link preview must not give the letter away.
        assert "Seni" not in html.split("<body")[0]
        answered = await client.post(f"/p/{page.token}/yes", data="{}", headers=JSON_HEADERS)
        assert answered.status == 200
        assert (await client.get("/demo/apology/romantik?lang=ru")).status == 200
    assert await db.scalar(
        text("SELECT answered_at IS NOT NULL FROM share_pages WHERE id = :i"), {"i": page.id}
    )


# --- through the bot ---------------------------------------------------------------------------


async def test_an_apology_is_made_in_the_bot_and_locks_once_forgiven(db: AsyncConnection) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=760_001, username="lola_bot")
    await bot.say(CATALOG["btn.menu.help"]["uz"], user=761)
    await bot.tap(PageMenuCB(action="apology").pack(), user=761)
    await bot.tap(PageLangCB(lang="ru").pack(), user=761)
    await bot.say("Прости меня, пожалуйста.\nЯ был неправ.", user=761)
    await bot.tap(PageTemplateCB(template="konvert").pack(), user=761)
    await bot.tap(PageChoiceCB(field="notify", value="yes").pack(), user=761)
    assert "Прости меня" in bot.last()
    await bot.tap(PageConfirmCB(action="create").pack(), user=761)
    row = (
        await db.execute(
            text(
                "SELECT id, token, kind, lang, template, message, notify_creator "
                "FROM share_pages WHERE shop_id = :s"
            ),
            {"s": bot.shop_id},
        )
    ).one()
    assert row[2:] == ("apology", "ru", "konvert", "Прости меня, пожалуйста.\nЯ был неправ.", True)
    assert any(f"/p/{row[1]}" in body for body in bot.texts())
    session = bound_session_factory(db)()
    await share_pages.answer_yes(session, row[1])
    await session.commit()
    await bot.tap(MyPageCB(action="edit", page_id=row[0]).pack(), user=761)
    assert bot.last() == CATALOG["pages.edit_locked"]["uz"]
    await bot.tap(EditFieldCB(page_id=row[0], field="message").pack(), user=761)
    assert bot.last() == CATALOG["pages.edit_locked"]["uz"]


async def test_another_shops_bot_cannot_touch_the_letter(db: AsyncConnection) -> None:
    a = ShopBot(db, await make_shop(db, "A"), bot_id=760_002, username="a_bot")
    b = ShopBot(db, await make_shop(db, "B"), bot_id=760_003, username="b_bot")
    await a.say(CATALOG["btn.menu.help"]["uz"], user=762)
    customer = await db.scalar(
        text("SELECT id FROM customers WHERE shop_id = :s AND telegram_user_id = 762"),
        {"s": a.shop_id},
    )
    session = bound_session_factory(db)()
    page = await share_pages.create_page(
        session, shop_id=a.shop_id, customer_id=int(customer), bot_username="a_bot", draft=draft()
    )
    await session.commit()
    await b.say(CATALOG["btn.menu.help"]["uz"], user=762)
    await b.tap(EditFieldCB(page_id=page.id, field="message").pack(), user=762)
    assert b.last() == CATALOG["pages.gone"]["uz"]
    await b.say("hacked", user=762)
    await b.tap(MyPageCB(action="open", page_id=page.id).pack(), user=762)
    assert all(LETTER not in body for body in b.texts())
    assert (
        await db.scalar(text("SELECT message FROM share_pages WHERE id = :i"), {"i": page.id})
        == LETTER
    )
