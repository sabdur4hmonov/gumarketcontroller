"""CP22 extraction, correction and ALL caption/image designs."""

import hashlib
import io
import json
from html import unescape
from pathlib import Path

import pytest
from PIL import Image, ImageFont

from gulbot.announcements.correction import Corrector, default_corrector
from gulbot.announcements.extraction import Fields, extract
from gulbot.announcements.images import FONT, IMAGE_STYLES, overlay
from gulbot.announcements.templates import CAPTION_STYLES, caption, utf16_length
from gulbot.catalog.hashtags import extract_hashtags
from gulbot.catalog.naming import product_name
from gulbot.catalog.prices import PriceConfidence, parse_price


@pytest.mark.parametrize(
    "text",
    [
        "Qizil atirgul, ellik bitta dona, narxi to'rt yuz ellik ming so'm",
        "Қизил атиргул, эллик битта дона, нархи тўрт юз эллик минг сўм",
        "atrgul qizil 51ta, narxi 450 ming so'm",
    ],
)
def test_flower_count_price(text):
    fields = extract(text)
    assert fields.flowers == ["atirgul"]
    assert fields.count == 51
    assert fields.price == 450000
    assert fields.colour == "qizil"
    assert fields.raw == text
    fields.validate()


def test_ambiguous_prices_need_edit():
    f = extract("oq atirgul 15 dona, narxi 450 ming so'm yoki 500 ming so'm")
    assert f.price is None
    assert f.warnings
    with pytest.raises(ValueError):
        f.validate()


def test_correction_protects_domain_numbers_and_preserves_description():
    corrector = Corrector(["tabrik", "atirgul", "ellik", "oq", "mehmon"])
    text = "atrgul ellik bitta dona. tabrk uchun! Alisher ♥"
    result = extract(text, corrector=corrector)
    assert result.description == "atrgul ellik bitta dona. tabrik uchun! Alisher ♥"
    assert result.corrections == ["tabrk → tabrik"]
    ambiguous = Corrector(["qalb", "qald"])
    assert ambiguous.correct("qalt", protected=[])[0] == "qalt"


def test_correction_keeps_urls_emails_and_handles():
    corrector = Corrector(["tabrik"])
    source = "tabrk https://tabrk.uz/joy @tabrk tabrk@example.uz #tabrk"
    corrected, changes = corrector.correct(source, protected=[])
    assert corrected == "tabrik https://tabrk.uz/joy @tabrk tabrk@example.uz #tabrk"
    assert len(changes) == 1


def test_missing_dictionary_keeps_text_entry_working(tmp_path, monkeypatch):
    from gulbot.announcements import correction

    correction.default_corrector.cache_clear()
    monkeypatch.setattr(correction, "ASSETS", tmp_path)
    try:
        fields = extract("oq atirgul 15 dona narxi 450 ming so'm")
        fields.validate()
        assert fields.price == 450000 and fields.count == 15
        assert fields.corrections == []
    finally:
        correction.default_corrector.cache_clear()


@pytest.mark.parametrize("text", ["qizil emas atirgul", "қизил эмас атиргул", "не красная роза"])
def test_negated_colour_is_not_a_confirmable_colour(text):
    fields = extract(text + " 15 dona 450 ming so'm")
    assert not fields.colour
    assert fields.warnings


def test_real_dictionary_loaded_both_scripts():
    c = default_corrector()
    assert len(c.words) > 100000
    assert "salom" in c.words
    assert "салом" in c.words


@pytest.mark.parametrize("directory", ["dictionary", "fonts"])
def test_vendored_sources_keep_their_pinned_bytes(directory):
    root = FONT.parents[1] / directory
    manifest = json.loads((root / "SOURCE.json").read_text(encoding="utf-8"))
    assert len(manifest["revision"]) == 40
    for item in manifest["files"]:
        original = (root / item["name"]).read_bytes()
        assert len(original) == item["bytes"]
        assert hashlib.sha256(original).hexdigest() == item["sha256"]


@pytest.mark.parametrize("style", CAPTION_STYLES)
@pytest.mark.parametrize("price", [10000, 450000, 50000000])
def test_every_caption_catalog_and_escaped_worst_case(style, price):
    fields = Fields(
        flowers=["atirgul", "tyulpan"],
        count=9999,
        price=price,
        colour="qizil",
        description="<b>& 😀 15 000 so'm #custom " * 150,
    )
    result = caption(fields, style=style, shop_name="<script> & 😀" * 100)
    assert utf16_length(result) <= 1024
    assert "<b>" not in result and "<script>" not in result
    visible = unescape(result)
    assert parse_price(visible) == (price, PriceConfidence.HIGH)
    assert product_name(visible) == "Atirgul, tyulpan buketi — 9999 dona"
    assert {"atirgul", "tyulpan", "buket"} <= set(extract_hashtags(visible))


def test_twenty_unique_styles():
    fields = Fields(flowers=["atirgul"], count=51, price=450000, colour="qizil")
    assert len(CAPTION_STYLES) == 20
    assert len({caption(fields, style=s, shop_name="Do'kon") for s in CAPTION_STYLES}) == 20


@pytest.mark.parametrize("style", ["none", *IMAGE_STYLES])
def test_every_image_original_render(style):
    source = io.BytesIO()
    Image.new("RGB", (900, 1200), "#c36481").save(source, format="JPEG")
    result = overlay(
        source.getvalue(),
        style=style,
        price=450000,
        shop_name="O'zbekiston — Ўзбекистон ҚҒҲ Ё 😀 " * 40,
    )
    with Image.open(io.BytesIO(result)) as photo:
        assert photo.width == 900 and photo.height == 1200
        assert not photo.getexif()
    assert FONT.exists()
    if style == "none":
        assert result == source.getvalue()
    else:
        assert result != source.getvalue()


def test_overlay_refuses_unknown_style():
    with pytest.raises(ValueError):
        overlay(b"", style="unknown", price=450000, shop_name="A")


def test_ofl_font_has_uzbek_and_cyrillic_glyphs():
    font = ImageFont.truetype(str(FONT), 36)
    missing = bytes(font.getmask(chr(0x10FFFF)))
    for char in "O'GʻўқғҳЁРоза":
        assert bytes(font.getmask(char)) != missing, char


def test_ten_bouquet_prompts_match_expected_fields():
    samples = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/cp22-samples.json").read_text(encoding="utf-8")
    )["samples"]
    assert len(samples) == 10
    for sample in samples:
        f = extract(sample["prompt"])
        assert {
            "flowers": f.flowers,
            "count": f.count,
            "price_uzs": f.price,
            "colour": f.colour,
        } == sample["expected_fields"], sample["id"]
