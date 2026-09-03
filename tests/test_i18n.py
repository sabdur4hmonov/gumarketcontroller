"""The i18n catalog must be complete and its button labels unambiguous."""

from __future__ import annotations

import pytest

from gulbot.i18n import t
from gulbot.i18n.catalog import BUTTON_KEYS, CATALOG, LANGUAGES
from gulbot.i18n.translator import button_labels


@pytest.mark.parametrize("lang", LANGUAGES)
def test_every_key_exists_in_every_language(lang: str) -> None:
    missing = [key for key, entry in CATALOG.items() if not entry.get(lang)]
    assert not missing, f"missing {lang} strings: {missing}"


def test_no_key_is_empty_or_whitespace() -> None:
    blank = [
        f"{key}.{lang}"
        for key, entry in CATALOG.items()
        for lang, value in entry.items()
        if not value.strip()
    ]
    assert not blank


def test_button_labels_are_unique_within_a_language() -> None:
    """Two buttons sharing a label make the (state, trigger) pair ambiguous."""
    for lang in LANGUAGES:
        labels = [CATALOG[key][lang] for key in BUTTON_KEYS]
        duplicates = {label for label in labels if labels.count(label) > 1}
        assert not duplicates, f"duplicate {lang} button labels: {duplicates}"


def test_unknown_key_returns_the_key_rather_than_raising() -> None:
    """A missing string must never take the bot down mid-conversation."""
    assert t("no.such.key", "uz") == "no.such.key"


def test_falls_back_to_default_language() -> None:
    assert t("menu.title", "de") == CATALOG["menu.title"]["uz"]


def test_formatting_placeholders_are_applied() -> None:
    assert "Aziz" in t("start.welcome_back", "uz", name="Aziz")


def test_missing_placeholder_does_not_raise() -> None:
    assert t("start.welcome_back", "uz") == CATALOG["start.welcome_back"]["uz"]


def test_button_labels_covers_both_languages() -> None:
    labels = button_labels()
    assert CATALOG["btn.menu.settings"]["uz"] in labels
    assert CATALOG["btn.menu.settings"]["ru"] in labels
