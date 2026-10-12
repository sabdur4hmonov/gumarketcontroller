"""360px browser checks for ALL designs, page kinds and four languages.

Install .[dev] plus Chrome, or point CP24_CHROME_PATH at an existing Chromium.
Missing browser tooling is a failure, not a silently skipped coverage claim.
One browser is shared; contexts run serially and are closed after each case.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import Browser
from tests.share_page_cp24_browser import audit_case, browser_world
from tests.share_page_cp24_cases import ALL_DESIGNS

from gulbot.models.share_page import PAGE_LANGUAGES, PageKind
from gulbot.web.designs_cp24 import CP24_DESIGNS


@pytest.fixture(scope="session")
def chrome_world() -> Iterator[tuple[Browser, str]]:
    with browser_world() as world:
        yield world


@pytest.mark.parametrize("theme", ALL_DESIGNS)
@pytest.mark.parametrize("kind", [str(k) for k in PageKind])
@pytest.mark.parametrize("lang", PAGE_LANGUAGES)
def test_worst_case_at_360_has_no_overflow_or_foreign_requests(
    chrome_world: tuple[Browser, str],
    theme: str,
    kind: str,
    lang: str,
) -> None:
    browser, origin = chrome_world
    result: dict[str, Any] = audit_case(browser, origin, theme, kind, lang)
    assert result["status"] == 200
    assert result["width"] == 360
    assert result["overflow"] == []
    assert result["seal_overflow"] == []
    assert result["external"] == []
    assert result["errors"] == []
    assert result["csp"] == []
    assert result["missingImages"] == []
    assert all(asset["status"] == 200 for asset in result["assets"])
    if theme in CP24_DESIGNS:
        assert result["sealed"] is True
        assert result["seal_label"] == ("ҚҒҲЎҚ" if lang == "uz_cyrl" else "WWWWW")
        assert result["font_bytes"] <= 110 * 1024
        assert result["chrome_bytes"] <= 180 * 1024
