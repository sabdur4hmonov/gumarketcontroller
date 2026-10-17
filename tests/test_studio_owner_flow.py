"""The owner's PC test, automated (CP27 fix A3): the whole studio as a customer
of a shop meets it, end to end, at 360 px in real headless Chrome.

The shop's bot runs on the fake Bot API (a recording session, no Telegram),
in studio-only mode as production will (the wizard off, pages on https). The
studio and the public pages are the real page server on real Postgres; the
studio link the bot sends is opened in the browser.

    /start -> language -> cancel -> "💌 Taklifnoma · Ha/Yo'q" -> "🌐 Taklifnoma yaratish"
    -> the link -> Kirish -> an invitation with two places (one Google Maps link)
    -> "O'zgartirish" (picker; premium locked) -> a design -> "Ko'rish" -> "Yaratish"
    -> the public page lists both places -> "Mening sahifalarim" -> edit (same link)
    -> delete (the public page is gone, the text scrubbed)
    -> one Ha/Yo'q page and one Uzrnoma; music and photos locked without the gift.

One screenshot per step goes to .cp22-stage/cp27/owner-flow/ (git-ignored,
private); the bot's steps are drawn as a small transcript page. Every browser
step is also checked: no overflow at 360 px, no other origin, no CSP
violation, no script error, AA contrast.
"""

# ruff: noqa: F811  (fixtures are imported by name)

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestServer
from playwright.async_api import Browser, Page
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.share_pages_harness import ShopBot, make_shop
from tests.test_studio_browser import AUDIT_JS, CSP_LISTENER, Watch, chrome  # noqa: F401
from tests.test_studio_web import DATE, app_for

from gulbot import config
from gulbot.bot.callbacks import PageMenuCB
from gulbot.i18n.catalog import CATALOG
from gulbot.web import links

pytestmark = pytest.mark.infra

SHOTS = Path(__file__).resolve().parents[1] / ".cp22-stage" / "cp27" / "owner-flow"
USER = 883_001
MAPS = "https://www.google.com/maps/place/Navroz/@41.311081,69.240562,17z"
LINK = re.compile(r"https?://[^\s]+/studio/enter/[A-Za-z0-9_-]{40,64}")


class OwnerWatch(Watch):
    """As the studio's browser runs, plus ONE expected answer: the public page
    after it was deleted is 410 Gone, by design."""

    def _expected(self, text: str, url: str) -> bool:
        gone = text.startswith("Failed to load resource") and "410" in text and "/p/" in url
        return gone or super()._expected(text, url)

    def _response(self, response: Any) -> None:
        if response.status == 410 and "/p/" in response.url:
            return
        super()._response(response)


class Steps:
    """Numbered screenshots, and the checks every browser step must pass."""

    def __init__(self) -> None:
        SHOTS.mkdir(parents=True, exist_ok=True)
        for old in SHOTS.glob("*.png"):
            old.unlink()
        self.n = 0
        self.names: list[str] = []

    def _path(self, name: str) -> Path:
        self.n += 1
        file = f"{self.n:02d}-{name}.png"
        self.names.append(file)
        return SHOTS / file

    async def browser(self, page: Page, name: str) -> None:
        height = await page.evaluate("document.documentElement.scrollHeight")
        for y in range(0, int(height), 700):
            await page.evaluate(f"window.scrollTo(0, {y})")
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path=str(self._path(name)), full_page=True)
        result = await page.evaluate(AUDIT_JS)
        assert result["overflow"] == [], (name, result["overflow"][:5])
        assert result["scroll"] <= 360, (name, result["scroll"])
        assert result["low"] == [], (name, result["low"][:5])
        assert result["csp"] == [], (name, result["csp"])

    async def bot(self, page: Page, name: str, bot: ShopBot, since: int) -> None:
        """The bot's replies since `since`, drawn as a plain chat transcript."""
        bubbles = []
        for body, markup in list(zip(bot.texts(), bot.markups(), strict=False))[since:]:
            plain = html.escape(re.sub(r"<[^>]+>", "", body)).replace("\n", "<br>")
            buttons = ""
            rows = getattr(markup, "inline_keyboard", None) or getattr(markup, "keyboard", None)
            for row in rows or []:
                buttons += "".join(f"<span class=b>{html.escape(b.text)}</span>" for b in row)
            bubbles.append(f"<div class=m>{plain}<div>{buttons}</div></div>")
        await page.set_content(
            "<!doctype html><meta charset=utf-8><style>"
            "body{font:15px system-ui;margin:0;padding:12px;background:#dfe7ee;color:#111}"
            ".m{background:#fff;border-radius:12px;padding:10px;margin:0 0 10px;"
            "overflow-wrap:anywhere}"
            ".b{display:inline-block;margin:6px 6px 0 0;padding:6px 10px;border-radius:8px;"
            "background:#e8f0fe;color:#123}</style>"
            f"<p><b>Bot</b> · {html.escape(name)}</p>{''.join(bubbles)}"
        )
        await page.screenshot(path=str(self._path(f"bot-{name}")), full_page=True)


def label(key: str) -> str:
    return CATALOG[key]["uz"]


async def test_the_owners_whole_flow_at_360px(
    db: AsyncConnection, chrome: Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Studio-only mode, as production with a domain.
    studio_only = config.get_settings().model_copy(
        update={"share_wizard_in_bot": False, "public_base_url": "https://pages.example.uz"}
    )
    monkeypatch.setattr(config, "get_settings", lambda: studio_only)
    shop = await make_shop(db, "Lola gullari")
    bot = ShopBot(db, shop, bot_id=424_601, username="lola_gullar_bot")

    server = TestServer(app_for(db))
    await server.start_server()
    origin = str(server.make_url("")).rstrip("/")
    # The link the bot sends points at THIS page server (the browser's origin).
    served = config.get_settings().model_copy(update={"public_base_url": origin})
    monkeypatch.setattr(links, "get_settings", lambda: served)

    watch = OwnerWatch(origin)
    context = await chrome.new_context(
        viewport={"width": 360, "height": 780},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    await context.add_init_script(CSP_LISTENER)
    watch.watch_context(context)
    steps = Steps()
    try:
        page = await context.new_page()
        watch.attach(page)
        chat = await context.new_page()  # the bot transcript, drawn locally

        # --- in the bot -------------------------------------------------------------
        await bot.say("/start", user=USER)
        await bot.say(label("btn.language.uz"), user=USER)
        await steps.bot(chat, "start-and-language", bot, 0)
        seen = len(bot.texts())
        await bot.say(label("btn.nav.cancel"), user=USER)
        await bot.say(label("btn.menu.pages"), user=USER)
        menu = bot.markups()[-1].inline_keyboard
        assert [[b.callback_data for b in row] for row in menu] == [
            [PageMenuCB(action="studio").pack()]
        ], "the pages menu must be the one studio button"
        await steps.bot(chat, "pages-menu", bot, seen)
        seen = len(bot.texts())
        await bot.tap(PageMenuCB(action="studio").pack(), user=USER)
        found = LINK.search(bot.last())
        assert found, bot.last()
        assert found.group(0).startswith(origin)
        await steps.bot(chat, "studio-link", bot, seen)
        await chat.close()

        # --- the link, in the browser ---------------------------------------------------
        await page.goto(found.group(0))
        await steps.browser(page, "kirish")
        await page.get_by_role("button", name="Kirish").click()
        await page.wait_for_url(f"{origin}/studio")
        await steps.browser(page, "form-empty")

        await page.fill('input[name="name_1"]', "Aziz")
        await page.fill('input[name="name_2"]', "Malika")
        await page.fill('input[name="event_date"]', DATE)
        await page.fill('input[name="venue_name_1"]', "Navro‘z to‘yxonasi")
        await page.fill('input[name="venue_address_1"]', "Chilonzor 5")
        await page.fill('input[name="venue_map_1"]', MAPS)
        await page.get_by_role("button", name="+ Joy qo‘shish").click()
        await page.wait_for_load_state()
        await page.fill('input[name="venue_name_2"]', "Kelin tomon uyi")
        await page.locator('label.chip:has(input[name="venue_kind_2"][value="uy"])').click()
        music = page.locator('select[name="music"] option[value="bahor"]')
        assert await music.get_attribute("disabled") is not None, "music offered without the gift"
        await steps.browser(page, "form-two-places-music-locked")

        await page.get_by_role("button", name="O‘zgartirish").click()
        await page.wait_for_url(f"{origin}/studio/design")
        await page.get_by_role("button", name="Hammasi").first.click()
        await page.wait_for_load_state()
        locked = page.locator('[data-design="deco"]')
        assert await locked.locator("button.choose").count() == 0, "a premium design offered"
        assert "🔒" in await locked.inner_text()
        await steps.browser(page, "picker-premium-locked")
        await page.locator('[data-design="tungi"] button.choose').click()
        await page.wait_for_load_state()
        assert await page.input_value('input[name="venue_name_2"]') == "Kelin tomon uyi"
        await steps.browser(page, "form-design-chosen")

        async with context.expect_page() as opened:
            await page.locator(".chosen button.link").click()
        preview = await opened.value
        watch.attach(preview)
        await preview.wait_for_load_state()
        assert "theme-tungi" in await preview.content()
        await steps.browser(preview, "preview")
        await preview.close()
        assert await db.scalar(text("SELECT count(*) FROM share_pages")) == 0

        await page.get_by_role("button", name="Yaratish").last.click()
        await page.wait_for_url(f"{origin}/studio/done/*")
        link = await page.input_value("#page-url")
        assert "🔒" in await page.locator("#s-photos").locator("..").inner_text()
        await steps.browser(page, "done-photos-locked")

        public = await context.new_page()
        watch.attach(public)
        await public.goto(link)
        body = await public.locator("body").inner_text()
        assert "Navro‘z to‘yxonasi" in body and "Kelin tomon uyi" in body, "both places"
        assert await public.locator(".venue-item").count() == 2
        assert await public.locator(f'a[href="{MAPS}"]').count() == 1
        await steps.browser(public, "public-page-two-places")

        # --- my pages: edit (same link), delete ------------------------------------------
        await page.get_by_role("link", name="Mening sahifalarim").click()
        await page.wait_for_url(f"{origin}/studio/pages")
        await steps.browser(page, "my-pages")
        await page.locator(".page-link").first.click()
        await page.wait_for_url(f"{origin}/studio/page/*")
        await page.get_by_role("link", name="Tahrirlash").click()
        await page.wait_for_url(f"{origin}/studio/page/*/edit")
        await page.fill('input[name="name_2"]', "Malikaxon")
        await steps.browser(page, "edit-form")
        await page.get_by_role("button", name="Saqlash").last.click()
        await page.wait_for_url(f"{origin}/studio/page/*")
        assert await page.input_value("#page-url") == link, "an edit changed the link"
        await public.reload()
        assert "Malikaxon" in await public.locator("body").inner_text()
        await steps.browser(page, "edited-same-link")

        await page.get_by_role("button", name="O‘chirish").click()
        await page.wait_for_url(f"{origin}/studio/page/*/delete")
        await steps.browser(page, "delete-confirm")
        await page.get_by_role("button", name="Ha, o‘chirilsin").click()
        await page.wait_for_url(f"{origin}/studio/pages")
        assert await page.locator(".page-link").count() == 0
        gone = await public.goto(link)
        assert gone is not None and gone.status == 410
        await steps.browser(public, "public-page-gone")
        row = (
            await db.execute(text("SELECT name_1, venue FROM share_pages ORDER BY id LIMIT 1"))
        ).one()
        assert (row.name_1, row.venue) == (None, None), "the text was not scrubbed"
        await public.close()

        # --- one Ha/Yo'q and one Uzrnoma ---------------------------------------------------
        await page.goto(f"{origin}/studio?kind=yesno")
        await page.locator('input[name="question_preset"][value="date"]').check()
        await steps.browser(page, "yesno-form")
        await page.get_by_role("button", name="Yaratish").last.click()
        await page.wait_for_url(f"{origin}/studio/done/*")
        await steps.browser(page, "yesno-done")

        await page.goto(f"{origin}/studio?kind=apology")
        await page.fill('textarea[name="letter"]', "Meni kechir, iltimos. Hammasi uchun uzr.")
        await steps.browser(page, "apology-form")
        await page.get_by_role("button", name="Yaratish").last.click()
        await page.wait_for_url(f"{origin}/studio/done/*")
        await steps.browser(page, "apology-done")
        kinds = list(await db.scalars(text("SELECT kind FROM share_pages ORDER BY id")))
        assert kinds == ["invite", "yesno", "apology"]
    finally:
        await context.close()
        await server.close()
    (SHOTS / "INDEX.txt").write_text("\n".join(steps.names) + "\n", encoding="utf-8")
    assert watch.foreign == [], watch.foreign
    assert watch.failed == [], watch.failed
    assert watch.errors == [], watch.errors
    assert watch.dialogs == []
