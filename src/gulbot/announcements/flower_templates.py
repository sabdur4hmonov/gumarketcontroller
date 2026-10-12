"""Captions for the 150 flower templates (CP23): theme x layout x language.

THE CATALOG HEADER IS FIXED, whatever the template: line 1 is the product's
name (CP8 `product_name` takes the first line with a letter in it) and line 2
is the labelled price CP7 `parse_price` reads with HIGH confidence, BEFORE any
owner text -- so a price inside the description can never win. Hashtags close
the caption: the theme's canonical tags and every flower extraction found.

Everything is HTML-escaped; the only tag the project adds is <b>. The owner's
shop name and description are fitted into what is left of Telegram's 1024
caption units, measured on the escaped HTML (stricter than what Telegram
counts, so the budget can never be exceeded).
"""

from __future__ import annotations

from html import escape

from .extraction import Fields
from .layouts import LAYOUT_IDS, LAYOUTS, Layout
from .templates import escaped_fit, utf16_length
from .themes import COLOUR_NAMES, FLOWER_NAMES, LANGS, NOT_A_FLOWER, THEMES, FlowerTheme, localized

CAPTION_LIMIT = 1024
SHOP_BUDGET = 160
ALL_TEMPLATES = tuple(f"{theme}.{layout}" for theme in THEMES for layout in LAYOUT_IDS)

_PRICE_LABEL = {"uz": "Narxi", "uz_cyrl": "Нархи", "ru": "Цена"}
_CURRENCY = {"uz": "so'm", "uz_cyrl": "сўм", "ru": "сум"}
_PIECES = {"uz": "dona", "uz_cyrl": "дона", "ru": "шт"}
_RULE = "┈┈┈┈┈┈┈┈┈┈"


def _esc(text: str) -> str:
    """HTML-escape for a Telegram caption; apostrophes stay readable (so'm)."""
    return escape(text, quote=False)


def split_template(template: str) -> tuple[FlowerTheme, Layout]:
    theme, _, layout = template.partition(".")
    if theme not in THEMES or layout not in LAYOUTS:
        raise ValueError("unknown template")
    return THEMES[theme], LAYOUTS[layout]


def money(price: int, lang: str) -> str:
    return f"{price:,} {_CURRENCY[lang]}".replace(",", " ")


def price_line(price: int, lang: str) -> str:
    return f"{_PRICE_LABEL[lang]}: {money(price, lang)}"


def title(fields: Fields, theme: FlowerTheme, lang: str) -> str:
    """The product name: the flowers, or the theme when it is only a form."""
    names = [
        localized(FLOWER_NAMES[flower], lang)
        for flower in dict.fromkeys(fields.flowers)
        if flower not in NOT_A_FLOWER and flower in FLOWER_NAMES
    ]
    count = f"{fields.count} {_PIECES[lang]}"
    if theme.id == "quti":
        head = theme.name(lang)
        return f"{head}: {', '.join(names)} — {count}" if names else f"{head} — {count}"
    if not names:
        return f"{theme.name(lang)} — {count}"
    joined = ", ".join(names)
    if lang == "ru":
        return f"Букет: {joined} — {count}"
    suffix = "гулдастаси" if lang == "uz_cyrl" else "guldastasi"
    return f"{joined[:1].upper()}{joined[1:]} {suffix} — {count}"


def hashtags(fields: Fields, theme: FlowerTheme) -> list[str]:
    return list(dict.fromkeys([*theme.hashtags, *fields.flowers, "buket"]))


def details(fields: Fields, lang: str) -> str:
    colour = localized(COLOUR_NAMES[fields.colour], lang) if fields.colour else ""
    count = f"{fields.count} {_PIECES[lang]}"
    return f"{colour} · {count}" if colour else count


def caption(fields: Fields, *, template: str, shop_name: str, lang: str = "uz") -> str:
    fields.validate()
    if lang not in LANGS:
        raise ValueError("unknown caption language")
    theme, layout = split_template(template)
    if fields.price is None:  # validate() refuses it; this keeps mypy honest
        raise ValueError("no price")
    lines = theme.lines(lang)
    marks = layout.mark.format(e=theme.emoji[0], e2=theme.emoji[1])
    heading_text = layout.text(layout.heading, lang)
    parts: dict[str, str] = {
        "heading": _esc(f"{marks} {heading_text}".strip()) if heading_text else "",
        "line": _esc(f"{theme.emoji[2]} {lines[layout.line]}"),
        "details": _esc(details(fields, lang)),
        "closing": _esc(layout.text(layout.closing, lang)),
        "rule": _RULE,
    }
    head = _esc(title(fields, theme, lang))
    price = _esc(price_line(fields.price, lang))
    if layout.id == "price_first":
        price = f"<b>💰 {price}</b>"
    elif layout.id == "premium":
        head = f"<b>{head}</b>"
    tags = " ".join(f"#{tag}" for tag in hashtags(fields, theme))

    fixed = [head, price, *(parts.get(name, "") for name in layout.order), tags]
    # +2: the newlines that the shop and description lines will add.
    used = utf16_length("\n".join(line for line in fixed if line)) + 2
    parts["shop"] = escaped_fit(f"📍 {shop_name}", min(SHOP_BUDGET, CAPTION_LIMIT - used))
    used += utf16_length(parts["shop"])
    parts["description"] = escaped_fit(fields.description, max(0, CAPTION_LIMIT - used))

    body = [parts[name] for name in layout.order]
    return "\n".join(line for line in [head, price, *body, tags] if line)
