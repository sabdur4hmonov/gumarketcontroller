"""The page flows speak uz, ru and en -- all of them, completely.

CP17 offers English to customers. English covers the way in (first contact,
language, menu, settings, navigation) and the Ha/Yo'q and taklifnoma flows in
full; everything else falls back to Uzbek. This file is what makes "in full"
true: a page-flow key added without its English, or without its Uzbek or
Russian, fails the build here -- whoever adds it does not have to remember.
"""

from __future__ import annotations

import re
import string

from gulbot.i18n import t
from gulbot.i18n.catalog import BUTTON_KEYS, CATALOG, TRILINGUAL_KEYS

THREE = ("uz", "ru", "en")

#: Every key of the page flows, present and future, must be trilingual.
PAGE_FLOW_PREFIXES = ("pages.", "ibtn.pages.", "ibtn.event.", "btn.menu.pages")


def page_flow_keys() -> set[str]:
    return {key for key in CATALOG if key.startswith(PAGE_FLOW_PREFIXES)}


def test_the_page_flows_are_not_an_empty_set() -> None:
    """Guards the guard: a prefix typo would make everything below vacuous."""
    assert len(page_flow_keys()) >= 70


def test_every_page_flow_key_is_held_to_three_languages() -> None:
    assert page_flow_keys() <= TRILINGUAL_KEYS, sorted(page_flow_keys() - TRILINGUAL_KEYS)


def test_every_trilingual_key_has_all_three() -> None:
    missing = [
        f"{key}.{lang}"
        for key in sorted(TRILINGUAL_KEYS)
        for lang in THREE
        if not (CATALOG.get(key, {}).get(lang) or "").strip()
    ]
    assert not missing, f"missing translations: {missing}"


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_the_three_translations_take_the_same_placeholders() -> None:
    """A {url} missing from one language would silently print nothing there."""
    drift = [
        key
        for key in sorted(TRILINGUAL_KEYS)
        if len({frozenset(_placeholders(CATALOG[key][lang])) for lang in THREE}) != 1
    ]
    assert not drift, f"placeholders differ between languages: {drift}"


def test_english_button_labels_are_unique() -> None:
    labels = [CATALOG[key]["en"] for key in BUTTON_KEYS if "en" in CATALOG[key]]
    duplicates = {label for label in labels if labels.count(label) > 1}
    assert not duplicates, duplicates


def test_html_tags_survive_translation() -> None:
    """The bot sends HTML; an unclosed <b> in one language breaks the message."""
    for key in sorted(TRILINGUAL_KEYS):
        for lang in THREE:
            text = CATALOG[key][lang]
            assert len(re.findall(r"<b>", text)) == len(re.findall(r"</b>", text)), (key, lang)


def test_an_english_customer_gets_english_here_and_uzbek_elsewhere() -> None:
    assert t("pages.menu", "en").startswith("What shall we make?")
    # A flow not yet translated falls back to Uzbek rather than to a key.
    assert t("occasions.empty", "en") == CATALOG["occasions.empty"]["uz"]
