"""`product_name`: the display name CP8 has to put in a NOT NULL column.

Pure, so these are plain input/output tests. The interesting cases are all the
ones where a caption is not the tidy two-line shape a designer imagines.
"""

from __future__ import annotations

import pytest

from gulbot.catalog.naming import (
    _PRICE_START,
    NAME_MAX_LENGTH,
    SINGLE_LINE_MAX_LENGTH,
    product_name,
)


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
    """The 200-character cap protects the column, and is reached through a
    MULTI-line caption whose first line is enormous.

    It used to be asserted with a single-line caption, which no longer reaches
    it: a caption with no line breaks takes the tighter one-line cut first (see
    the section at the end of this file), so 500 characters come back as 60.
    That is the new rule working rather than a regression -- but the column cap
    still needs a guard, and this is the shape that still exercises it.
    """
    assert len(product_name("A" * 500 + "\nNarxi: 150 000 so'm")) == NAME_MAX_LENGTH


def test_a_single_line_caption_takes_the_tighter_cut_instead() -> None:
    """The other half of the pair above, so the difference is on the page."""
    assert len(product_name("A" * 500)) == SINGLE_LINE_MAX_LENGTH


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


# --- the one-line caption -------------------------------------------------
#
# Added after a real post arrived written as a single run. "First line" is only
# a good rule when the florist used line breaks; without them the whole caption
# became the name, so every reminder would carry 56 characters with the price
# stated twice.

#: Exactly what was posted to the shop's channel on 2026-09-07, backslashes and
#: all -- the florist typed a backslash where they meant a line break.
REAL_ONE_LINE_CAPTION = "#lola Nafis atirgul buketi\\ 15 dona\\ Narxi: 150 000 so'm\\buket"

#: The same bouquet reposted properly, which is the shape the admin guidance
#: asks for.
REAL_MULTI_LINE_CAPTION = "🌹 Nafis atirgul buketi\n15 dona\nNarxi: 150 000 so'm\n#lola"


def test_the_real_multi_line_post_is_untouched() -> None:
    """The common case must not be disturbed to protect the rare one."""
    assert product_name(REAL_MULTI_LINE_CAPTION) == "\U0001f339 Nafis atirgul buketi"


def test_the_real_one_line_post_loses_its_price_tail() -> None:
    """The caption that prompted this. Everything from "Narxi:" onwards is price
    information, not a name."""
    name = product_name(REAL_ONE_LINE_CAPTION)
    assert "Narxi" not in name
    assert "150 000" not in name
    assert name.startswith("Nafis atirgul buketi")
    assert len(name) < len(REAL_ONE_LINE_CAPTION)


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        # The price marker is a currency word after the figure...
        ("Oq lola buketi 25 dona 300 000 so'm", "Oq lola buketi 25 dona"),
        # ...or a price word before it...
        ("Qizil atirgul buketi 51 ta Narxi: 450 000 so'm #atirgul", "Qizil atirgul buketi 51 ta"),
        # ...or the k-form, which the price parser also reads as a price.
        ("Bahor buketi 150k #buket", "Bahor buketi"),
        # Cyrillic vocabulary, same rule, because both come from the parser.
        ("Красные розы 25 шт Цена: 300 000 сум", "Красные розы 25 шт"),
    ],
)
def test_a_one_line_caption_stops_where_the_price_starts(caption: str, expected: str) -> None:
    assert product_name(caption) == expected


def test_a_caption_that_opens_with_its_price_keeps_the_name_after_it() -> None:
    """Written the other way round, the name FOLLOWS the price. Taking the text
    before the marker would return nothing at all."""
    assert product_name("Narxi: 150 000 so'm atirgul buketi") == "atirgul buketi"


def test_a_long_one_line_caption_with_no_price_is_cut_on_a_word_boundary() -> None:
    """No price marker to aim at, so the only remaining protection is length --
    and a name must not end mid-word."""
    caption = "Juda chiroyli va nafis bahorgi atirgul buketi katta o'lchamda tayyorlandi"
    name = product_name(caption)
    assert len(name) <= SINGLE_LINE_MAX_LENGTH
    assert caption.startswith(name)
    assert caption[len(name)] == " ", "the cut landed mid-word"


def test_a_short_one_line_caption_is_left_alone() -> None:
    """The trim is a safety net, not a routine edit."""
    assert product_name("Atirgul buketi") == "Atirgul buketi"


@pytest.mark.parametrize("separator", ["-", "|", "/", "\u2022", ","])
def test_separators_do_not_dangle_off_the_end_of_a_cut_name(separator: str) -> None:
    """A florist's field separator becomes a trailing tail once the field after
    it is removed."""
    assert product_name("Atirgul buketi " + separator + " Narxi: 150 000 so'm") == "Atirgul buketi"


def test_the_price_vocabularies_are_shared_with_the_parser() -> None:
    """Guards against the two drifting apart. A price word the parser learns and
    the namer does not would put a price back into a name."""
    from gulbot.catalog import prices

    assert prices.PRICE_WORDS in _PRICE_START.pattern
    assert prices.CURRENCY_WORDS in _PRICE_START.pattern
