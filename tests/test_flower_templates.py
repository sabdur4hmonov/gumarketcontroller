"""CP23 phase 1: 15 flower themes x 10 layouts = 150 templates, all of them.

Every check below runs over EVERY combination (and every caption language),
parametrised from the data, never a hand-picked sample:

  * the caption is catalogue-compatible: CP8's name is the controlled title,
    CP7 reads the labelled price with HIGH confidence, and the hashtags are
    the theme's canonical ones plus every flower found;
  * the worst case fits Telegram's 1024-unit caption limit, measured on the
    escaped HTML (stricter than Telegram's own count);
  * all owner text is escaped; the only markup is the project's <b>;
  * the overlay never lets text leave its panel or the photo, for a long
    shop name and a 9-digit price, on portrait, landscape and tiny photos.
"""

from __future__ import annotations

import io
import re
from html import unescape

import pytest
from PIL import Image

from gulbot.announcements.designs import contrast, post_canvas, render_post, text_on
from gulbot.announcements.extraction import Fields, extract
from gulbot.announcements.flower_templates import (
    ALL_TEMPLATES,
    caption,
    money,
    split_template,
    title,
)
from gulbot.announcements.layouts import LAYOUT_IDS, LAYOUTS
from gulbot.announcements.lexicon import COLOURS, FLOWERS
from gulbot.announcements.motifs import load, raster
from gulbot.announcements.script import to_cyrillic
from gulbot.announcements.templates import utf16_length
from gulbot.announcements.themes import (
    COLOUR_NAMES,
    FLOWER_NAMES,
    FLOWER_THEME,
    LANGS,
    THEMES,
    theme_for,
)
from gulbot.catalog.alias_fixture import ALIASES
from gulbot.catalog.hashtags import extract_hashtags, normalize_hashtag
from gulbot.catalog.naming import product_name
from gulbot.catalog.prices import PriceConfidence, parse_price

#: The brief's flowers, by theme id.
BRIEF = {
    "atirgul",
    "kust_atirgul",
    "lola",
    "xrizantema",
    "gerbera",
    "liliya",
    "pion",
    "gortenziya",
    "eustoma",
    "chinnigul",
    "orxideya",
    "alstromeriya",
    "mimoza",
    "aralash",
    "quti",
}
HOSTILE = "<b>& 😀 15 000 so'm #custom <script>alert(1)</script> " * 60
LONG_SHOP = "Gullar olami — Chilonzor filiali, Toshkent shahri, Bunyodkor ko'chasi 12"
LATIN = re.compile(r"[A-Za-z]")
CYRILLIC = re.compile(r"[А-Яа-яЁёЎўҚқҒғҲҳ]")


def worst_fields(template: str, price: int) -> Fields:
    theme, _ = split_template(template)
    # Eight flowers is the most a draft may hold; the theme's own first.
    own = [key for key, value in FLOWER_THEME.items() if value == theme.id][:1]
    others = [key for key in FLOWER_NAMES if key not in own and key in FLOWERS][: 8 - len(own)]
    return Fields(
        flowers=[*own, *others],
        count=9999,
        price=price,
        colour="ochpushti",
        description=HOSTILE,
    )


# --- the system ---------------------------------------------------------------


def test_fifteen_themes_ten_layouts_one_hundred_fifty_templates() -> None:
    assert set(THEMES) == BRIEF
    assert len(LAYOUTS) == 10
    assert len(ALL_TEMPLATES) == len(set(ALL_TEMPLATES)) == 150


@pytest.mark.parametrize("theme_id", sorted(THEMES))
def test_every_theme_is_complete(theme_id: str) -> None:
    theme = THEMES[theme_id]
    assert 2 <= len(theme.palettes) <= 3
    assert len(theme.emoji) >= 3 and all(theme.emoji)
    for palette in theme.palettes:
        assert set(palette.colours) <= set(COLOURS), palette
    assert len(theme.lines_uz) == len(theme.lines_ru) == 3
    # Every colour a variety claims is a real lexicon colour, and the variety
    # a bouquet's colour picks is the one that claims it.
    for palette in theme.palettes:
        for colour in palette.colours:
            assert colour in {c for p in theme.palettes for c in p.colours}
    first_claim = {}
    for palette in theme.palettes:
        for colour in palette.colours:
            first_claim.setdefault(colour, palette)
    for colour, palette in first_claim.items():
        assert theme.palette_for(colour) == palette
    assert theme.palette_for("no-such-colour") == theme.palettes[0]


@pytest.mark.parametrize("theme_id", sorted(THEMES))
def test_every_text_colour_pair_is_readable(theme_id: str) -> None:
    for palette in THEMES[theme_id].palettes:
        for surface in (palette.bg, palette.ink, palette.soft):
            ratio = contrast(text_on(palette, surface), surface)
            assert ratio >= 4.5, (palette.name, surface, round(ratio, 2))


@pytest.mark.parametrize("theme_id", sorted(THEMES))
def test_every_theme_hashtag_is_one_the_catalogue_resolves(theme_id: str) -> None:
    known = {normalize_hashtag(k) for k in ALIASES} | {
        normalize_hashtag(v) for v in ALIASES.values()
    }
    for tag in THEMES[theme_id].hashtags:
        assert normalize_hashtag(tag) in known, tag


@pytest.mark.parametrize("theme_id", sorted(THEMES))
def test_every_theme_has_its_own_original_motif(theme_id: str) -> None:
    motif = THEMES[theme_id].motif
    assert motif == theme_id
    assert load(motif)
    art = raster(motif, 120, "#123456")
    assert art.size == (120, 120)
    assert art.getchannel("A").getbbox() is not None, "the motif drew nothing"


@pytest.mark.parametrize("theme_id", sorted(THEMES))
def test_wording_in_three_scripts_without_mixing(theme_id: str) -> None:
    theme = THEMES[theme_id]
    for line in theme.lines("uz"):
        assert not CYRILLIC.search(line), line
    for lang in ("uz_cyrl", "ru"):
        for line in (*theme.lines(lang), theme.name(lang)):
            assert not LATIN.search(line), (lang, line)
    for layout in LAYOUTS.values():
        for pair in (layout.heading, layout.closing, layout.badge, layout.label):
            assert not LATIN.search(layout.text(pair, "uz_cyrl")), pair
            assert not LATIN.search(layout.text(pair, "ru")), pair


def test_every_lexicon_flower_and_colour_has_a_display_name() -> None:
    assert set(FLOWERS) <= set(FLOWER_NAMES)
    assert set(COLOURS) == set(COLOUR_NAMES)


def test_transliteration_of_project_text() -> None:
    assert to_cyrillic("Sevgingizni so'zsiz izhor qiling") == "Севгингизни сўзсиз изҳор қилинг"
    assert to_cyrillic("Yangi uyg'ongan bahor ranglari") == "Янги уйғонган баҳор ранглари"
    assert to_cyrillic("Etti xil gul, ma'no va mehr") == "Этти хил гул, маъно ва меҳр"
    assert to_cyrillic("8-Mart uchun") == "8-Март учун"
    assert to_cyrillic("YANGI") == "ЯНГИ"
    assert to_cyrillic("SOVG'A") == "СОВҒА"


# --- which theme ----------------------------------------------------------------


@pytest.mark.parametrize(("flower", "theme"), sorted(FLOWER_THEME.items()))
def test_one_flower_is_its_own_theme(flower: str, theme: str) -> None:
    assert theme_for([flower]) == theme
    assert theme_for([flower, "buket"]) == theme


@pytest.mark.parametrize(
    ("flowers", "text", "expected"),
    [
        (["atirgul", "tyulpan"], "", "aralash"),
        (["buket"], "", "aralash"),
        (["gipsofila"], "", "aralash"),
        ([], "", "aralash"),
        (["atirgul"], "Qizil atirgul qutida, 25 dona", "quti"),
        (["atirgul", "tyulpan"], "QIZIL atirgullar va oq тюльпаны, maxsus quti bilan.", "quti"),
        (["pion"], "Пионы в коробке", "quti"),
        (["atirgul"], "qutlug' bo'lsin, atirgullar", "atirgul"),
    ],
)
def test_mixed_and_boxed(flowers: list[str], text: str, expected: str) -> None:
    assert theme_for(flowers, text) == expected


def test_extraction_finds_the_new_theme_flowers() -> None:
    assert extract("Kust atirgul 15 dona, narxi 300 000 so'm").flowers == ["kustatirgul"]
    assert extract("Мимоза 9 штук, цена 120 000 сум").flowers == ["mimoza"]
    assert extract("Oq liliya 7 dona, narxi 250 000 so'm").flowers == ["nilufar"]


# --- captions, all 150 x 3 languages --------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("template", ALL_TEMPLATES)
@pytest.mark.parametrize("price", [10_000, 450_000, 50_000_000])
def test_every_caption_is_catalogue_compatible_escaped_and_fits(
    template: str, lang: str, price: int
) -> None:
    fields = worst_fields(template, price)
    result = caption(fields, template=template, shop_name="<script>&😀" * 80, lang=lang)
    assert utf16_length(result) <= 1024
    assert "<script>" not in result and "&lt;script&gt;" in result
    assert set(re.findall(r"</?[a-z]+>", result)) <= {"<b>", "</b>"}
    visible = unescape(re.sub(r"</?b>", "", result))
    theme, _ = split_template(template)
    assert parse_price(visible) == (price, PriceConfidence.HIGH)
    assert product_name(visible) == title(fields, theme, lang)
    # Independent of hashtags(): every flower found, the theme's own tags, #buket.
    assert {*fields.flowers, *theme.hashtags, "buket"} <= set(extract_hashtags(visible))


@pytest.mark.parametrize("lang", LANGS)
def test_one_bouquet_gets_150_different_captions(lang: str) -> None:
    fields = Fields(flowers=["atirgul"], count=51, price=450_000, colour="qizil", description="")
    captions = {caption(fields, template=t, shop_name="Do'kon", lang=lang) for t in ALL_TEMPLATES}
    assert len(captions) == 150


def test_an_ordinary_caption_reads_well() -> None:
    fields = Fields(
        flowers=["atirgul"], count=51, price=450_000, colour="qizil", description="Yetkazib beramiz"
    )
    text = caption(fields, template="atirgul.classic", shop_name="Gulshan", lang="uz")
    assert text.splitlines()[:2] == ["Atirgul guldastasi — 51 dona", "Narxi: 450 000 so'm"]
    assert text.endswith("#atirgul #buket")
    ru = caption(fields, template="atirgul.classic", shop_name="Gulshan", lang="ru")
    assert ru.splitlines()[:2] == ["Букет: розы — 51 шт", "Цена: 450 000 сум"]


def test_project_text_is_escaped_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """A future line with "&" or "<" must not break Telegram's HTML."""
    from dataclasses import replace

    from gulbot.announcements import flower_templates

    risky = replace(THEMES["atirgul"], lines_uz=("Sevgi & <mehr>",) * 3)
    monkeypatch.setitem(flower_templates.THEMES, "atirgul", risky)
    fields = Fields(flowers=["atirgul"], count=5, price=100_000, colour="qizil")
    text = caption(fields, template="atirgul.classic", shop_name="A", lang="uz")
    assert "Sevgi &amp; &lt;mehr&gt;" in text and "<mehr>" not in text


def test_caption_refuses_an_unknown_template_or_language() -> None:
    fields = Fields(flowers=["atirgul"], count=1, price=10_000, colour="qizil")
    with pytest.raises(ValueError):
        caption(fields, template="atirgul.nope", shop_name="A")
    with pytest.raises(ValueError):
        caption(fields, template="nope.classic", shop_name="A")
    with pytest.raises(ValueError):
        caption(fields, template="atirgul.classic", shop_name="A", lang="de")


# --- overlays, all 150, three photo shapes --------------------------------------


def photo(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "#c36481").save(out, format="JPEG")
    return out.getvalue()


SHAPES = {"portrait": photo(900, 1200), "landscape": photo(1600, 900), "tiny": photo(300, 300)}


def inside(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


@pytest.mark.parametrize("shape", sorted(SHAPES))
@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_no_overlay_text_overflows(template: str, shape: str) -> None:
    lang = LANGS[ALL_TEMPLATES.index(template) % 3]
    rendered = render_post(
        SHAPES[shape],
        template=template,
        price=999_999_999,
        colour="pushti",
        shop_name=LONG_SHOP,
        lang=lang,
    )
    canvas = post_canvas(SHAPES[shape])
    assert (rendered.width, rendered.height) == canvas.size
    roles = {box.role for box in rendered.boxes}
    assert "price" in roles and "shop" in roles
    for box in rendered.boxes:
        assert inside(box.drawn, box.container), box
        assert inside(box.container, (0, 0, rendered.width, rendered.height)), box
        if box.role == "price":
            assert box.text == money(999_999_999, lang) and not box.truncated
    with Image.open(io.BytesIO(rendered.jpeg)) as image:
        assert image.size == canvas.size and not image.getexif()


def test_overlay_refuses_bad_input() -> None:
    with pytest.raises(ValueError):
        render_post(SHAPES["tiny"], template="atirgul.nope", price=1, colour="", shop_name="")
    with pytest.raises(ValueError):
        render_post(b"x" * 10_000_001, template="atirgul.classic", price=1, colour="", shop_name="")


def test_layout_ids_are_callback_safe() -> None:
    for template in ALL_TEMPLATES:
        assert ":" not in template and len(template) <= 30
    assert set(LAYOUT_IDS) == set(LAYOUTS)


# --- the motifs themselves ------------------------------------------------------


def test_the_committed_svgs_are_exactly_what_the_generator_draws() -> None:
    import importlib.util
    from pathlib import Path

    from gulbot.announcements.motifs import MOTIF_DIR

    script = Path(__file__).resolve().parents[1] / "scripts" / "motifs_cp23.py"
    spec = importlib.util.spec_from_file_location("motifs_cp23", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    drawn = module.render_all()
    committed = {p.stem: p.read_text(encoding="utf-8") for p in MOTIF_DIR.glob("*.svg")}
    assert committed == drawn


@pytest.mark.parametrize(
    "d",
    [
        "M 0 0 A 10 10 0 0 1 20 20",  # arcs are outside the subset
        "M 0 0 L 10",  # truncated
        "10 10 L 20 20",  # no command first
        "M 0 0 Z 5 5",  # numbers after Z
        "M 0 0 L 10 10 url(#x)",
    ],
)
def test_path_data_outside_the_subset_is_refused(d: str) -> None:
    from gulbot.announcements.motifs import MotifError, parse_path

    with pytest.raises(MotifError):
        parse_path(d)


def test_path_data_inside_the_subset_flattens() -> None:
    from gulbot.announcements.motifs import parse_path

    [(points, closed)] = parse_path(
        "M 0 0 l 10 0 C 10 10 20 10 20 0 S 30 -10 30 0 Q 35 5 40 0 T 50 0 Z"
    )
    assert closed and points[0] == (0.0, 0.0) and (10.0, 0.0) in points
    assert points[-1] == (50.0, 0.0)


@pytest.mark.parametrize(
    "svg",
    [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><rect width="5"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
        '<g transform="scale(2)"><circle cx="1" cy="1" r="1"/></g></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
        '<circle cx="1" cy="1" r="1" fill="red"/></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>',
    ],
)
def test_an_svg_outside_the_subset_is_refused(svg: str, tmp_path, monkeypatch) -> None:
    from gulbot.announcements import motifs

    (tmp_path / "bad.svg").write_text(svg, encoding="utf-8")
    monkeypatch.setattr(motifs, "MOTIF_DIR", tmp_path)
    motifs.load.cache_clear()
    try:
        with pytest.raises(motifs.MotifError):
            motifs.load("bad")
    finally:
        motifs.load.cache_clear()


def test_a_rasterised_motif_is_cached() -> None:
    first = raster("lola", 96, "#336699")
    assert raster("lola", 96, "#336699") is first
    assert raster("lola", 96, "#996633") is not first
