"""Taklifnoma Studio in real headless Chrome at 360 px (CP27.1).

The real page server (aiohttp, real Postgres in the test's transaction) and
the real browser, in one event loop. Each screen must have: no horizontal
overflow, no request to any other origin, no CSP violation, no script error,
and every visible text at WCAG AA contrast against what is behind it. The
form is also driven end to end: in by the bot's link, worst-case strings,
a second place, a design, "Ko'rish" in a new tab, "Yaratish", the copy button.

Install .[dev] plus Chrome, or point CP24_CHROME_PATH at an existing Chromium.
Missing browser tooling is a failure, not a skipped claim. Screenshots go to
.cp22-stage/cp27/ (git-ignored, private).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestServer
from playwright.async_api import Browser, Page, async_playwright
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.test_studio_web import DATE, app_for, mint, world  # noqa: F401  (fixture)

pytestmark = pytest.mark.infra

SHOTS = Path(__file__).resolve().parents[1] / ".cp22-stage" / "cp27"
HOSTILE = "<script>alert(1)</script>\"'&<img src=x onerror=alert(2)>"
LONG_CYRL = "Қўшимчаисмсизбирсўзузун" * 3  # one unbroken word, 69 letters
LONG_LATN = "Wxyz" * 40
#: CP27.1b: the empty form at 360 px, CSS px (it was ~6,200 with forty cards inline).
FORM_MAX_HEIGHT = 2600

#: Runs in the page: what a person would see that breaks the rules.
AUDIT_JS = """
() => {
  const vw = document.documentElement.clientWidth;
  const overflow = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (r.width === 0 || style.visibility === 'hidden' || el.closest('.default-submit')) continue;
    if (r.right > vw + 0.5 || r.left < -0.5) overflow.push(el.tagName + '.' + el.className);
  }
  const parse = (c) => (c.match(/[\\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const behind = (el) => {
    for (let n = el; n; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c.length === 3 || (c.length === 4 && c[3] === 1)) return c.slice(0, 3);
      if (getComputedStyle(n).backgroundImage !== 'none') return null;  // gradient: skip
    }
    return [255, 255, 255];
  };
  const low = [];
  for (const el of document.querySelectorAll('body *')) {
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    const style = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (r.width === 0 || style.visibility === 'hidden' || el.closest('.default-submit')) continue;
    const bg = behind(el);
    if (!bg) continue;
    const fg = parse(style.color).slice(0, 3);
    const [a, b] = [lum(fg) + 0.05, lum(bg) + 0.05];
    const ratio = Math.max(a, b) / Math.min(a, b);
    const size = parseFloat(style.fontSize);
    const large = size >= 24 || (size >= 18.66 && Number(style.fontWeight) >= 700);
    if (ratio < (large ? 3 : 4.5)) {
      low.push(el.tagName + ':' + el.textContent.trim().slice(0, 30) + ':' + ratio.toFixed(2));
    }
  }
  return {width: vw, scroll: document.documentElement.scrollWidth, overflow, low,
          height: document.documentElement.scrollHeight,
          csp: window.__csp || []};
}
"""

CSP_LISTENER = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', (e) => {
  window.__csp.push(e.violatedDirective + ' ' + e.blockedURI);
});
"""


@pytest_asyncio.fixture
async def chrome() -> AsyncIterator[Browser]:
    async with async_playwright() as pw:
        executable = os.environ.get("CP24_CHROME_PATH")
        options: dict[str, Any] = (
            {"executable_path": executable} if executable else {"channel": "chrome"}
        )
        browser = await pw.chromium.launch(headless=True, args=["--disable-gpu"], **options)
        try:
            yield browser
        finally:
            await browser.close()


class Watch:
    """Every request, console error, page error and dialog of one context."""

    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.foreign: list[str] = []
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        self.failed: list[str] = []

    def watch_context(self, context: Any) -> None:
        """Requests and responses of every tab, the preview's from its first."""
        context.on("request", self._request)
        context.on("response", self._response)

    def attach(self, page: Page) -> None:
        page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        page.on(
            "console",
            lambda msg: (
                self.errors.append(f"{msg.text} @ {msg.location.get('url')}")
                if msg.type == "error" and not self._expected(msg.text, msg.location.get("url", ""))
                else None
            ),
        )
        page.on("dialog", self._dialog)

    def _request(self, request: Any) -> None:
        url = request.url
        if not (url.startswith(self.origin) or url.startswith("data:")):
            self.foreign.append(url)

    def _expected(self, text: str, url: str) -> bool:
        """Chrome's own favicon probe (the server has none, by design) and the
        form's 422 refusal page; every other console error fails the test."""
        loading = text.startswith("Failed to load resource")
        return loading and (
            ("404" in text and url == f"{self.origin}/favicon.ico")
            or ("422" in text and url == f"{self.origin}/studio/create")
        )

    def _response(self, response: Any) -> None:
        # The form's own refusal is a 422 document by design; nothing else may fail.
        expected = response.status == 422 and response.request.resource_type == "document"
        if response.status >= 400 and not expected:
            self.failed.append(f"{response.status} {response.url}")

    async def _dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        await dialog.dismiss()


async def audit(page: Page, name: str) -> dict[str, Any]:
    SHOTS.mkdir(parents=True, exist_ok=True)
    # Scroll as a person would, so the lazy thumbnails load before the shot.
    height = await page.evaluate("document.documentElement.scrollHeight")
    for y in range(0, int(height), 700):
        await page.evaluate(f"window.scrollTo(0, {y})")
        await page.wait_for_timeout(30)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_load_state("networkidle")
    await page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
    result: dict[str, Any] = await page.evaluate(AUDIT_JS)
    assert result["width"] == 360, name
    assert result["overflow"] == [], (name, result["overflow"][:10])
    assert result["scroll"] <= 360, (name, result["scroll"])
    assert result["low"] == [], (name, result["low"][:10])
    assert result["csp"] == [], (name, result["csp"])
    return result


async def test_the_studio_at_360px_end_to_end(
    world: dict[str, Any],  # noqa: F811
    chrome: Browser,
) -> None:
    db: AsyncConnection = world["db"]
    server = TestServer(app_for(db))
    await server.start_server()
    origin = str(server.make_url("")).rstrip("/")
    watch = Watch(origin)
    context = await chrome.new_context(
        viewport={"width": 360, "height": 780},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    await context.grant_permissions(["clipboard-read", "clipboard-write"], origin=origin)
    await context.add_init_script(CSP_LISTENER)
    watch.watch_context(context)
    try:
        page = await context.new_page()
        watch.attach(page)

        # In by the bot's link: the GET shows Kirish, the button spends it.
        raw = await mint(db, world["a"], world["ca"])
        await page.goto(f"{origin}/studio/enter/{raw}")
        await audit(page, "01-enter")
        await page.get_by_role("button", name="Kirish").click()
        await page.wait_for_url(f"{origin}/studio")
        empty = await audit(page, "02-form-empty")
        # CP27.1b: the data form is short; the forty designs live on their own screen.
        assert empty["height"] <= FORM_MAX_HEIGHT, empty["height"]

        # Worst-case strings, then a mistake: the form comes back with them.
        await page.fill('input[name="name_1"]', (HOSTILE + LONG_CYRL)[:60])
        await page.fill('input[name="name_2"]', LONG_LATN[:60])
        await page.fill('input[name="venue_name_1"]', (HOSTILE + LONG_LATN)[:80])
        await page.fill('input[name="venue_address_1"]', (LONG_CYRL * 3)[:160])
        await page.fill('input[name="venue_map_1"]', "https://evil.example/x")
        await page.fill('textarea[name="message"]', (HOSTILE + LONG_CYRL * 6)[:400])
        await page.fill('input[name="event_date"]', DATE)
        await page.get_by_role("button", name="Yaratish").last.click()
        await page.wait_for_load_state()
        await page.get_by_text("Xarita havolasi Google").wait_for()
        await audit(page, "03-form-worst-case-error")

        # A second place, a kind chip, a real map link, a design.
        await page.fill('input[name="venue_map_1"]', "https://maps.app.goo.gl/abc123")
        await page.get_by_role("button", name="+ Joy qo‘shish").click()
        await page.wait_for_load_state()
        await page.locator('input[name="venue_name_2"]').fill("Kelin tomon")
        await page.locator('label.chip:has(input[name="venue_kind_2"][value="uy"])').click()
        await audit(page, "04-form-two-places")

        # The picker: its own screen, filters, a choice, back to the same form.
        await page.get_by_role("button", name="O‘zgartirish").click()
        await page.wait_for_url(f"{origin}/studio/design")
        await page.get_by_role("button", name="Hammasi").first.click()
        await page.wait_for_load_state()
        await audit(page, "05-picker-all")
        await page.locator('[data-design="tungi"] button.choose').click()
        await page.wait_for_load_state()
        assert await page.input_value('input[name="venue_name_2"]') == "Kelin tomon"
        assert await page.locator('.chosen[data-design="tungi"]').count() == 1
        await audit(page, "06-form-design-chosen")

        # "Ko'rish" opens the real page in a new tab, saved nowhere.
        async with context.expect_page() as opened:
            await page.locator(".chosen button.link").click()
        preview = await opened.value
        watch.attach(preview)
        await preview.wait_for_load_state()
        assert "theme-tungi" in await preview.content()
        await preview.screenshot(path=str(SHOTS / "07-preview.png"))
        await preview.close()

        await page.get_by_role("button", name="Yaratish").last.click()
        await page.wait_for_url(f"{origin}/studio/done/*")
        await audit(page, "08-done")
        copy = page.get_by_role("button", name="Nusxalash")
        await copy.click()
        await page.get_by_role("button", name="Nusxalandi ✓").wait_for()
        link = await page.input_value("#page-url")
        assert "/p/" in link
    finally:
        await context.close()
        await server.close()
    assert watch.foreign == [], watch.foreign
    assert watch.failed == [], watch.failed
    assert watch.errors == [], watch.errors
    assert watch.dialogs == [], "typed markup ran as script"


async def test_yesno_apology_and_photos_at_360px(
    world: dict[str, Any],  # noqa: F811
    chrome: Browser,
) -> None:
    """CP27.2: the other two kinds, music and a real photo upload, at 360 px."""
    from tests.test_share_page_photos import phone_photo
    from tests.test_studio_kinds import gift

    db: AsyncConnection = world["db"]
    await gift(db, world["a"], world["ca"])
    server = TestServer(app_for(db))
    await server.start_server()
    origin = str(server.make_url("")).rstrip("/")
    watch = Watch(origin)
    context = await chrome.new_context(
        viewport={"width": 360, "height": 780},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    await context.add_init_script(CSP_LISTENER)
    watch.watch_context(context)
    photo = SHOTS / "upload.jpg"
    SHOTS.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(phone_photo(1600, 1200))
    try:
        page = await context.new_page()
        watch.attach(page)
        raw = await mint(db, world["a"], world["ca"])
        await page.goto(f"{origin}/studio/enter/{raw}")
        await page.get_by_role("button", name="Kirish").click()
        await page.wait_for_url(f"{origin}/studio")

        await page.get_by_role("link", name="Ha / Yo‘q").click()
        await page.wait_for_url(f"{origin}/studio?kind=yesno")
        await page.locator('input[name="question_preset"][value="custom"]').check()
        await page.fill('input[name="question"]', (HOSTILE + LONG_CYRL)[:140])
        await page.select_option('select[name="music"]', "bahor")
        await audit(page, "11-yesno-form")
        await page.get_by_role("button", name="Yaratish").last.click()
        await page.wait_for_url(f"{origin}/studio/done/*")
        await audit(page, "12-yesno-done")
        await page.set_input_files('input[name="photo"]', str(photo))
        await page.get_by_role("button", name="Yuklash").click()
        await page.wait_for_url(f"{origin}/studio/done/*")
        await page.get_by_text("(1/1)").wait_for()
        await audit(page, "13-yesno-photo")

        await page.goto(f"{origin}/studio?kind=apology")
        await page.fill('textarea[name="letter"]', (HOSTILE + LONG_CYRL * 6)[:400])
        await audit(page, "14-apology-form")
        await page.get_by_role("button", name="Yaratish").last.click()
        await page.wait_for_url(f"{origin}/studio/done/*")
        await audit(page, "15-apology-done")
    finally:
        await context.close()
        await server.close()
        photo.unlink(missing_ok=True)
    assert watch.foreign == [], watch.foreign
    assert watch.failed == [], watch.failed
    assert watch.errors == [], watch.errors
    assert watch.dialogs == [], "typed markup ran as script"
