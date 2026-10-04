"""The twenty designs: each one complete, self-contained and readable in
Uzbek Cyrillic.

* Every design in PAGE_TEMPLATES has its stylesheet, its theme colour, its
  name and its picker icon -- a design added in one place and forgotten in
  another fails here, not on a customer's phone.
* Every font a theme names is one we ship, declared in fonts.css or
  fonts_cp17.css, with its license file beside it.
* A theme that leads with a face lacking Қ Ғ Ҳ (checked glyph by glyph, see
  static/fonts/LICENSES.md) must set `--font-display-uzc` to a complete one.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from gulbot.bot.keyboards_pages import THEME_ICONS
from gulbot.models.share_page import PAGE_TEMPLATES
from gulbot.web.render import STATIC, THEME_COLORS, THEME_NAMES

#: Faces without the full Uzbek Cyrillic set (Қ Ғ Ҳ), from the glyph check.
INCOMPLETE_FOR_UZBEK_CYRILLIC = frozenset(
    {
        "Great Vibes",
        "Unbounded",
        "Comfortaa",
        "Poiret One",
        "El Messiri",
        "Prata",
        "Old Standard TT",
        "Kurale",
    }
)
GENERIC = frozenset({"serif", "sans-serif", "cursive", "monospace"})
SYSTEM = frozenset({"Georgia", "Arial", "Segoe UI", "Arial Narrow", "Comic Sans MS", "Roboto"})


def declared_families() -> set[str]:
    text = "".join(
        (STATIC / "css" / name).read_text(encoding="utf-8")
        for name in ("fonts.css", "fonts_cp17.css")
    )
    return set(re.findall(r'font-family: "([^"]+)"', text))


def css(theme: str) -> str:
    return (STATIC / "css" / f"theme-{theme}.css").read_text(encoding="utf-8")


def families(value: str) -> list[str]:
    return [part.strip().strip('"') for part in value.split(",")]


def variable(source: str, name: str) -> str | None:
    match = re.search(rf"{re.escape(name)}:\s*([^;]+);", source)
    return match.group(1).strip() if match else None


def test_there_are_twenty_designs() -> None:
    assert len(PAGE_TEMPLATES) == 20
    assert len(set(PAGE_TEMPLATES)) == 20


@pytest.mark.parametrize("theme", PAGE_TEMPLATES)
def test_every_design_is_complete(theme: str) -> None:
    assert (STATIC / "css" / f"theme-{theme}.css").is_file()
    assert theme in THEME_COLORS and theme in THEME_NAMES and theme in THEME_ICONS


@pytest.mark.parametrize("theme", PAGE_TEMPLATES)
def test_every_named_font_is_one_we_ship(theme: str) -> None:
    shipped = declared_families()
    source = css(theme)
    for name in ("--font-display", "--font-display-uzc", "--font-body"):
        value = variable(source, name)
        if value is None or value.startswith("var("):
            continue
        for family in families(value):
            assert family in shipped or family in GENERIC or family in SYSTEM, (theme, family)


@pytest.mark.parametrize("theme", PAGE_TEMPLATES)
def test_uzbek_cyrillic_never_falls_into_a_face_without_its_letters(theme: str) -> None:
    source = css(theme)
    display = variable(source, "--font-display")
    if display is None:
        return  # base.css: Cormorant Garamond, complete
    lead = families(display)[0]
    if lead not in INCOMPLETE_FOR_UZBEK_CYRILLIC:
        return
    fallback = variable(source, "--font-display-uzc")
    assert fallback is not None, f"{theme} leads with {lead} and sets no --font-display-uzc"
    assert families(fallback)[0] not in INCOMPLETE_FOR_UZBEK_CYRILLIC, (theme, fallback)


def test_every_shipped_family_has_its_license_beside_it() -> None:
    fonts = STATIC / "fonts"
    for family in declared_families():
        slug = family.lower().replace(" ", "-")
        assert (fonts / f"{slug}-OFL.txt").is_file(), family


def test_no_theme_reaches_outside_this_origin() -> None:
    for theme in PAGE_TEMPLATES:
        assert "http" not in css(theme).replace("http://www.w3.org/2000/svg", ""), theme


@pytest.mark.infra
async def test_the_migrated_database_admits_every_design(db: AsyncConnection) -> None:
    """The CHECK the migrations built -- not the model's -- names every design:
    a design the migration forgot would be refused on a customer's tap."""
    definition = await db.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_share_pages_template_known'"
        )
    )
    assert definition is not None
    for theme in PAGE_TEMPLATES:
        assert f"'{theme}'" in definition, theme
