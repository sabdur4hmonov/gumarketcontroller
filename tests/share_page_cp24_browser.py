"""Local-only real browser harness for share-page layout, CSP and byte evidence."""

from __future__ import annotations

import mimetypes
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Browser, expect, sync_playwright
from tests.share_page_cp24_cases import ALL_DESIGNS, case_html

from gulbot.models.share_page import PAGE_LANGUAGES, PageKind
from gulbot.web.app import CSP
from gulbot.web.render import STATIC


class CaseHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        request = urlparse(self.path)
        if request.path == "/case":
            q = parse_qs(request.query)
            theme, kind, lang = (q.get(key, [""])[0] for key in ("theme", "kind", "lang"))
            if (
                theme not in ALL_DESIGNS
                or kind not in tuple(PageKind)
                or lang not in PAGE_LANGUAGES
            ):
                self.send_error(404)
                return
            data = case_html(theme, kind, lang, worst=q.get("worst") == ["1"]).encode()
            mime = "text/html; charset=utf-8"
        elif request.path.startswith("/static/"):
            target = (STATIC / request.path.removeprefix("/static/")).resolve()
            if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
                self.send_error(404)
                return
            data = target.read_bytes()
            mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.end_headers()
        self.wfile.write(data)


@contextmanager
def browser_world() -> Iterator[tuple[Browser, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), CaseHandler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as pw:
            executable = os.environ.get("CP24_CHROME_PATH")
            options: dict[str, Any] = (
                {"executable_path": executable} if executable else {"channel": "chrome"}
            )
            browser = pw.chromium.launch(headless=True, args=["--disable-gpu"], **options)
            try:
                yield browser, f"http://127.0.0.1:{server.server_port}"
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


INIT = """(() => {
  window.cp24Csp = [];
  document.addEventListener('securitypolicyviolation', e => {
    window.cp24Csp.push(e.violatedDirective);
  });
  window.cp24Audio = 0;
  const Original = window.AudioContext;
  if (Original) window.AudioContext = new Proxy(Original, {construct(target, args) {
    window.cp24Audio++; return Reflect.construct(target, args);
  }});
})();"""

MEASURE = """() => {
  const selectors = 'h1,h2,p,button,a,label,dd,dt,.when-side,.when-month,'
    + '.cd-lbl,.program-item,.shop-brand';
  const overflow = [...document.querySelectorAll(selectors)].filter(el => {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    if (rect.width < 1 || rect.height < 1 || style.display === 'none'
        || style.visibility === 'hidden') return false;
    return rect.right > 360.5 || rect.left < -.5
      || (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 2);
  }).map(el => ({tag: el.tagName, cls: el.className, text: el.textContent.slice(0,40),
    scroll:el.scrollWidth, width:el.clientWidth}));
  return {overflow, width:document.documentElement.scrollWidth,
    csp:window.cp24Csp, audio:window.cp24Audio,
    missingImages:[...document.images].filter(i => !i.complete || !i.naturalWidth)
      .map(i=>i.src)};
}"""


def audit_case(
    browser: Browser,
    origin: str,
    theme: str,
    kind: str,
    lang: str,
    *,
    worst: bool = True,
    screenshot: Path | None = None,
    seal_screenshot: Path | None = None,
) -> dict[str, Any]:
    # Fresh context: browser cache cannot turn a warm visit into a cold-size claim.
    context = browser.new_context(
        viewport={"width": 360, "height": 800},
        device_scale_factor=1,
        reduced_motion="reduce",
        is_mobile=True,
        has_touch=True,
    )
    try:
        page = context.new_page()
        page.add_init_script(INIT)
        external: list[str] = []
        errors: list[str] = []
        responses: list[Any] = []
        page.on(
            "request",
            lambda r: external.append(r.url) if not r.url.startswith(origin + "/") else None,
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("response", lambda response: responses.append(response))
        status = page.goto(
            f"{origin}/case?theme={theme}&kind={kind}&lang={lang}&worst={int(worst)}",
            wait_until="networkidle",
        )
        page.evaluate("document.fonts.ready")
        sealed = page.locator("#seal").count() > 0
        seal_label = page.locator("#seal").inner_text() if sealed else None
        seal_overflow = []
        if sealed:
            # The seal is hidden after opening: measure its actual text range now.
            seal_overflow = page.locator("#seal").evaluate("""(seal) => {
              const range = document.createRange(); range.selectNodeContents(seal);
              const box = seal.getBoundingClientRect(), text = range.getBoundingClientRect();
              if (!seal.textContent.trim()) return [];
              const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
              const radius = Math.min(box.width, box.height) / 2 - 5;
              return [[text.left,text.top],[text.right,text.top],
                [text.left,text.bottom],[text.right,text.bottom]]
                .filter(([x,y]) => Math.hypot(x-cx,y-cy) > radius + 1)
                .map(([x,y]) => ({x,y,radius}));
            }""")
            if seal_screenshot:
                seal_screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(seal_screenshot))
            page.locator("#seal").click()
            expect(page.locator("body")).to_have_class(re.compile(r".*\bis-opened\b.*"))
            page.locator(".card > :not(.is-shown)").first.wait_for(state="detached")
            page.locator("#envelope").wait_for(state="hidden")
        # Loading lazy photos by scrolling models a real visit and prevents
        # a missing-image/weight check from examining never-requested images.
        for photo in page.locator("img").all():
            photo.scroll_into_view_if_needed()
            # Native decode() can reject for a still-deferred lazy image.
            # Observe actual readiness after scrolling without masking broken sources.
            deadline = time.monotonic() + 5
            while not photo.evaluate("(image) => image.complete && image.naturalWidth > 0"):
                if time.monotonic() >= deadline:
                    break
                page.wait_for_timeout(50)
        page.evaluate("window.scrollTo(0, 0)")
        measured: dict[str, Any] = page.evaluate(MEASURE)
        # Chromium's default audio policy must not be the only autoplay guard.
        assert measured["audio"] == 0
        if theme in ("zarhal", "sitrus", "lavha", "kadr") and lang == "uz":
            page.locator("#music").click()
            assert page.evaluate("window.cp24Audio") == 1
            assert page.locator("#music").get_attribute("aria-pressed") == "true"
            page.locator("#music").click()
            assert page.locator("#music").get_attribute("aria-pressed") == "false"
        if screenshot:
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot), full_page=True)
        assets = [
            {"path": urlparse(r.url).path, "status": r.status, "bytes": len(r.body())}
            for r in responses
        ]
        font_bytes = sum(a["bytes"] for a in assets if a["path"].endswith(".woff2"))
        photo_bytes = sum(a["bytes"] for a in assets if a["path"].endswith(".svg"))
        measured.update(
            status=status.status if status else 0,
            external=external,
            errors=errors,
            assets=assets,
            font_bytes=font_bytes,
            photo_bytes=photo_bytes,
            chrome_bytes=sum(a["bytes"] for a in assets) - photo_bytes,
            sealed=sealed,
            seal_label=seal_label,
            seal_overflow=seal_overflow,
        )
        return measured
    finally:
        context.close()
