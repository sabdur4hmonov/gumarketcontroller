"""CP24 artwork preflight: real HTTP/CSP and all designs × kinds × languages.

The pending catalog is deliberately absent from persistent creation until CP23
lands. No fixture inserts new design names ahead of the additive migration.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import pytest
from aiohttp.test_utils import TestClient, TestServer
from markupsafe import escape
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.share_page_cp24_cases import ALL_DESIGNS, HOSTILE, case_html
from tests.test_web_designs import declared_families, families, variable

from gulbot.models.share_page import EVENT_TYPES, PAGE_LANGUAGES, PAGE_TEMPLATES, PageKind
from gulbot.services.premium import CP24_PREMIUM_TEMPLATES
from gulbot.web import render, strings
from gulbot.web.app import CSP, build_app
from gulbot.web.designs_cp24 import CP24_DESIGNS


@pytest.fixture
async def demo_client() -> AsyncIterator[TestClient]:
    async def notify(_page_id: int, _delay: float = 0) -> None:
        pass

    app = build_app(
        session_factory=async_sessionmaker(), notify=notify, public_base_url="http://127.0.0.1:8774"
    )
    async with TestClient(TestServer(app)) as client:
        yield client


def test_twenty_new_keys_never_replace_original_designs() -> None:
    assert len(CP24_DESIGNS) == 20
    assert not set(PAGE_TEMPLATES) & set(CP24_DESIGNS)
    assert len(set(ALL_DESIGNS)) == 40
    assert all(len(key) <= 16 and re.fullmatch("[a-z]+", key) for key in CP24_DESIGNS)


def test_cp24_gift_selection_is_twelve_premium_and_eight_free() -> None:
    assert {
        "zarhal",
        "zumrad",
        "anor",
        "girih",
        "gulshabnam",
        "maktub",
        "sahro",
        "lavha",
        "kadr",
        "zinalar",
        "marjon",
        "moviy",
    } == CP24_PREMIUM_TEMPLATES
    assert set(CP24_DESIGNS) - CP24_PREMIUM_TEMPLATES == {
        "sitrus",
        "chiziq",
        "kamalak",
        "ilm",
        "anjuman",
        "navroz",
        "qish",
        "sokin",
    }


@pytest.mark.parametrize("theme", CP24_DESIGNS)
def test_artwork_fonts_and_bytes_are_self_contained(theme: str) -> None:
    css = (render.STATIC / "css" / f"theme-{theme}.css").read_text(encoding="utf-8")
    assert "http" not in css and "@import" not in css
    assert len(css.encode()) < 4096
    for prop in ("--font-display", "--font-display-uzc", "--font-body"):
        value = variable(css, prop)
        assert value is not None
        assert families(value)[0] in declared_families()
        assert families(value)[0] in {
            "Forum",
            "Lora",
            "Montserrat",
            "Nunito",
            "Cormorant Garamond",
            "Oswald",
            "Balsamiq Sans",
        }
    assert CP24_DESIGNS[theme].name.strip() and CP24_DESIGNS[theme].icon.strip()
    assert variable(css, "--bg") == CP24_DESIGNS[theme].color
    assert CP24_DESIGNS[theme].color == render.THEME_COLORS[theme]
    assert CP24_DESIGNS[theme].name == render.THEME_NAMES[theme]
    body = case_html(theme, "yesno", "uz")
    assert 'id="seal"' in body and "has-envelope" in body
    assert "css/cp24.css" in body


@pytest.mark.parametrize("theme", ALL_DESIGNS)
@pytest.mark.parametrize("kind", [str(k) for k in PageKind])
@pytest.mark.parametrize("lang", PAGE_LANGUAGES)
async def test_every_design_kind_language_renders_200_without_foreign_assets(
    demo_client: TestClient,
    theme: str,
    kind: str,
    lang: str,
) -> None:
    response = await demo_client.get(f"/demo/{kind}/{theme}?lang={lang}")
    assert response.status == 200
    assert response.headers["Content-Security-Policy"] == CSP
    body = await response.text()
    assert f'lang="{strings.HTML_LANG[lang]}"' in body
    assert f"theme-{theme}" in body
    assert not re.search(r"<script(?![^>]*\bsrc=)", body)
    assert " style=" not in body and "<style" not in body
    assert not re.search(r"\son[a-z]+=", body)
    assets = re.findall(r'<(?:script|img)[^>]+src="([^"]+)"|<link[^>]+href="([^"]+)"', body)
    assert assets
    for pair in assets:
        url = next(x for x in pair if x)
        assert url.startswith("/static/")
        assert (await demo_client.get(url)).status == 200
    hostile = case_html(theme, kind, lang, worst=True)
    assert HOSTILE not in hostile
    assert "&lt;script&gt;" in hostile and "<img src=x" not in hostile
    assert 'id="music"' in hostile
    assert "/demo/none/go" in hostile
    if kind == "invite":
        for marker in (
            'id="countdown"',
            "program-rows",
            "swatches",
            "gallery-grid",
            'id="rsvp-count"',
            'id="wish-form"',
        ):
            assert marker in hostile
    else:
        assert 'id="no"' in hostile and "data-lines=" in hostile


@pytest.mark.parametrize("theme", ALL_DESIGNS)
@pytest.mark.parametrize("event", EVENT_TYPES)
@pytest.mark.parametrize("lang", PAGE_LANGUAGES)
def test_each_event_is_content_neutral_in_every_design(theme: str, event: str, lang: str) -> None:
    sample = render.sample_page("invite", theme, lang, event_type=event)
    html = render.page_html(
        sample, render.Branding("Gulzor", "/go"), tz_name="Asia/Tashkent", base="/p/demo"
    )
    assert str(escape(strings.event_label(event, lang))) in html
    assert "None" not in html and "Undefined" not in html


@pytest.mark.parametrize("theme", ["lavha", "kadr"])
@pytest.mark.parametrize("kind", [str(k) for k in PageKind])
def test_photo_first_consumes_one_gallery_photo_and_obeys_gallery_switch(
    theme: str,
    kind: str,
) -> None:
    html = case_html(theme, kind, "uz")
    assert html.count("/static/cp24/sample-1.svg") == 1
    assert html.count("/static/cp24/sample-2.svg") == 1
    page = render.sample_page(kind, theme, "uz")
    page.show_gallery = False
    photo = render.PhotoLink("/private-photo.jpg", 480, 600)
    html = render.page_html(
        page,
        render.Branding("Gulzor", "/go"),
        tz_name="Asia/Tashkent",
        base="/p/demo",
        photos=[photo],
    )
    assert "/private-photo.jpg" not in html
    assert "photo-ph" in html


def test_palette_labels_cover_all_four_languages() -> None:
    from gulbot.web.sections import DRESS_PALETTE

    expected = {
        "Оқ",
        "Қора",
        "Олтин",
        "Кумуш",
        "Беж",
        "Пушти",
        "Қизил",
        "Бордо",
        "Лаванда",
        "Ҳаворанг",
        "Кўк",
        "Яшил",
    }
    assert {labels["uz_cyrl"] for _hex, labels in DRESS_PALETTE.values()} == expected
    assert all(set(labels) == set(PAGE_LANGUAGES) for _hex, labels in DRESS_PALETTE.values())


def test_twenty_new_ornaments_are_drawn_and_distinct() -> None:
    motifs = []
    for theme in CP24_DESIGNS:
        html = case_html(theme, "yesno", "uz")
        match = re.search(r'<svg class="ornament".*?</svg>', html, re.S)
        assert match is not None
        geometry = re.findall(r"<(?:path|circle|ellipse)[^>]+>", match[0])
        assert len(geometry) >= 1, theme
        motifs.append(tuple(geometry))
    assert len(set(motifs)) == 20


def test_cp24_font_declarations_have_licensed_complete_families() -> None:
    css = (render.STATIC / "css" / "fonts_cp24.css").read_text(encoding="utf-8")
    names = set(re.findall(r'font-family: "([^"]+)"', css))
    assert names == {
        "Forum",
        "Lora",
        "Montserrat",
        "Nunito",
        "Cormorant Garamond",
        "Oswald",
        "Balsamiq Sans",
    }
    for family in names:
        slug = family.lower().replace(" ", "-")
        licence = render.STATIC / "fonts" / f"{slug}-OFL.txt"
        assert "SIL OPEN FONT LICENSE Version 1.1" in licence.read_text(encoding="utf-8")
    urls = re.findall(r'url\("([^"?]+)"\)', css)
    assert len(urls) == 21
    assert all((render.STATIC / "css" / url).is_file() for url in urls)
    assert "http" not in css and "@import" not in css


def luminance(hex_value: str) -> float:
    channels = [int(hex_value[n : n + 2], 16) / 255 for n in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * w for c, w in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("theme", CP24_DESIGNS)
def test_shop_brand_and_primary_buttons_have_readable_contrast(theme: str) -> None:
    css = (render.STATIC / "css" / f"theme-{theme}.css").read_text(encoding="utf-8")
    for ink, surface in (("--shop-ink", "--bg"), ("--accent-ink", "--accent")):
        foreground, background = variable(css, ink), variable(css, surface)
        assert foreground is not None and background is not None
        assert contrast(foreground, background) >= 4.5, (theme, ink, surface)
    assert ".shop .fine { color: var(--shop-ink); opacity: 1; }" in css
