"""Lookup with an explicit fallback chain."""

from __future__ import annotations

from typing import Any

from gulbot.brand import brand_name
from gulbot.i18n.catalog import BRAND, BUTTON_KEYS, CATALOG, DEFAULT_LANGUAGE


def t(key: str, lang: str = DEFAULT_LANGUAGE, /, **kwargs: Any) -> str:
    """Translate `key` into `lang`.

    Falls back to the default language, then to the key itself. It never raises:
    a missing string must not take the bot down mid-conversation. The parity
    test is what keeps missing strings from reaching production in the first
    place.

    `{brand}` is the product's name (CP19), filled here for every string, so no
    caller passes it. A plain replace, not format: a string with literal braces
    and no arguments must still come back unchanged.
    """
    entry = CATALOG.get(key)
    if entry is None:
        return key
    template = entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key
    if BRAND in template:
        template = template.replace(BRAND, brand_name())
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def button_labels() -> set[str]:
    """Every button label in every language.

    The shadowing sweep probes the live dispatcher with each of these, so a
    button added to the catalog is automatically covered by the gate.
    """
    return {CATALOG[key][lang] for key in BUTTON_KEYS for lang in CATALOG[key]}
