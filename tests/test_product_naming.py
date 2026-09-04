"""`product_name`: the display name CP8 has to put in a NOT NULL column.

Pure, so these are plain input/output tests. The interesting cases are all the
ones where a caption is not the tidy two-line shape a designer imagines.
"""

from __future__ import annotations

import pytest

from gulbot.catalog.naming import NAME_MAX_LENGTH, product_name


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("Qizil atirgul buketi", "Qizil atirgul buketi"),
        # The first line is the name; the price line and the tags are not.
        ("Qizil atirgul buketi\nNarxi: 450 000 so'm\n#atirgul", "Qizil atirgul buketi"),
        # Tags inline with the name are stripped, not left dangling.
        ("Bahor buketi #atirgul #lola", "Bahor buketi"),
        ("#atirgul Bahor buketi", "Bahor buketi"),
        ("Bahor #atirgul buketi", "Bahor buketi"),
        # A leading blank or decorative line is skipped, not returned.
        ("\n\nBahor buketi", "Bahor buketi"),
        ("***\nBahor buketi", "Bahor buketi"),
        # Whitespace inside the line collapses; the line itself is trimmed.
        ("  Bahor    buketi  \nNarx", "Bahor buketi"),
        # Apostrophes are display text here, unlike in a hashtag key.
        ("Gulbog'i buketi", "Gulbog'i buketi"),
    ],
)
def test_the_name_is_the_first_real_line(caption: str, expected: str) -> None:
    assert product_name(caption) == expected


@pytest.mark.parametrize("caption", [None, "", "   ", "\n\n", "#atirgul", "#atirgul #lola", "***"])
def test_a_caption_with_no_name_in_it_returns_empty(caption: str | None) -> None:
    """Legitimate, and not an error: a photo captioned only with hashtags is a
    normal post. The indexer falls back to the first tag."""
    assert product_name(caption) == ""


def test_the_name_is_capped() -> None:
    assert len(product_name("A" * 500)) == NAME_MAX_LENGTH


def test_the_cap_matches_the_column() -> None:
    """A name longer than the column is an insert failure at 3am, not a test
    failure now."""
    from gulbot.models.product import Product

    assert Product.__table__.c.name.type.length == NAME_MAX_LENGTH


def test_invisible_characters_are_removed() -> None:
    """Zero-width marks survive copy-paste and render as nothing."""
    assert product_name("Bahor​ buketi") == "Bahor buketi"


def test_a_tab_does_not_fuse_two_words() -> None:
    """The same bug CP3's label sanitiser had: stripping a separator outright
    turns two words into one."""
    assert product_name("Bahor\tbuketi") == "Bahor buketi"
