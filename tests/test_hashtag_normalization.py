"""The hashtag normalisation matrix.

Every apostrophe variant, both scripts, case variants, and the adversarial
numeric tags that must NOT enter the hashtag keyspace.
"""

from __future__ import annotations

import pytest

from gulbot.catalog.hashtags import APOSTROPHES, extract_hashtags, normalize_hashtag

# --- apostrophes -----------------------------------------------------------

SOM_VARIANTS = [
    "so'm",  # U+0027 straight
    "so’m",  # U+2019 right single quote
    "so‘m",  # U+2018 left single quote
    "soʼm",  # U+02BC modifier letter apostrophe
    "soʻm",  # U+02BB modifier letter turned comma (correct Uzbek o')
    "so`m",  # U+0060 backtick
    "so´m",  # U+00B4 acute
]


@pytest.mark.parametrize("variant", SOM_VARIANTS)
def test_every_apostrophe_variant_of_som_normalizes_the_same(variant: str) -> None:
    assert normalize_hashtag(variant) == "som"


def test_all_som_variants_collapse_to_one_key() -> None:
    """The point of the exercise: one key, not seven."""
    assert len({normalize_hashtag(v) for v in SOM_VARIANTS}) == 1


@pytest.mark.parametrize("apostrophe", list(APOSTROPHES))
def test_each_declared_apostrophe_is_actually_stripped(apostrophe: str) -> None:
    assert normalize_hashtag(f"o{apostrophe}zbek") == "ozbek"


def test_uzbek_words_with_two_apostrophes() -> None:
    assert normalize_hashtag("#gulo'g'li") == "gulogli"


# --- case ------------------------------------------------------------------


@pytest.mark.parametrize("written", ["roza", "Roza", "ROZA", "RoZa", "rOZA"])
def test_case_variants_collapse(written: str) -> None:
    assert normalize_hashtag(written) == "roza"


@pytest.mark.parametrize("written", ["роза", "Роза", "РОЗА"])
def test_cyrillic_case_variants_collapse(written: str) -> None:
    assert normalize_hashtag(written) == "роза"


# --- scripts stay distinct -------------------------------------------------
#
# Latin and Cyrillic spellings normalise to DIFFERENT keys on purpose. The
# hashtag_aliases table maps them onto one canonical tag; transliterating here
# would silently merge words that are not the same word.

FLOWER_PAIRS = [
    ("roza", "роза"),
    ("tyulpan", "тюльпан"),
    ("lola", "лола"),
    ("atirgul", "атиргул"),
    ("chinnigul", "чиннигул"),
    ("nargis", "наргис"),
]


@pytest.mark.parametrize(("latin", "cyrillic"), FLOWER_PAIRS)
def test_both_scripts_normalize_without_crashing(latin: str, cyrillic: str) -> None:
    assert normalize_hashtag(latin) == latin
    assert normalize_hashtag(cyrillic) == cyrillic


@pytest.mark.parametrize(("latin", "cyrillic"), FLOWER_PAIRS)
def test_scripts_are_kept_distinct_for_the_alias_table_to_join(latin: str, cyrillic: str) -> None:
    """Not a bug: aliases do this mapping as data, where a human can edit it."""
    assert normalize_hashtag(latin) != normalize_hashtag(cyrillic)


@pytest.mark.parametrize(("latin", "cyrillic"), FLOWER_PAIRS)
def test_case_and_hash_do_not_change_the_script_outcome(latin: str, cyrillic: str) -> None:
    assert normalize_hashtag(f"#{latin.upper()}") == latin
    assert normalize_hashtag(f"#{cyrillic.upper()}") == cyrillic


# --- punctuation and hashes ------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("#roza", "roza"),
        ("##roza", "roza"),
        ("#roza!", "roza"),
        ("  #roza  ", "roza"),
        ("#roza.", "roza"),
        ("#roza,", "roza"),
        ("#(roza)", "roza"),
        ("#roza-buket", "rozabuket"),
        ("#roza_buket", "roza_buket"),
        ("#🌹roza", "roza"),
    ],
)
def test_punctuation_and_decoration_are_stripped(raw: str, expected: str) -> None:
    assert normalize_hashtag(raw) == expected


def test_digits_alongside_letters_survive() -> None:
    assert normalize_hashtag("#roza2024") == "roza2024"


# --- the adversarial numeric cases -----------------------------------------


@pytest.mark.parametrize(
    "numeric",
    [
        "#150000",
        "#150 000",
        "#998901234567",
        "#+998901234567",
        "#90-123-45-67",
        "#2024",
        "#1",
        "#150.000",
    ],
)
def test_numeric_tags_never_enter_the_hashtag_keyspace(numeric: str) -> None:
    """A price or a phone number is not a product tag.

    Letting these through would put numbers in the same keyspace as flower
    names, where a search for a bouquet could match a phone number.
    """
    assert normalize_hashtag(numeric) == ""


def test_a_price_shaped_tag_cannot_collide_with_a_real_one() -> None:
    real = {normalize_hashtag(t) for t in ("roza", "atirgul", "tyulpan")}
    assert normalize_hashtag("#150000") not in real
    assert "" not in real


@pytest.mark.parametrize("empty", ["", "#", "###", "   ", "!!!", "#!", "🌸", "#—"])
def test_nothing_usable_returns_empty(empty: str) -> None:
    assert normalize_hashtag(empty) == ""


# --- extraction ------------------------------------------------------------


def test_extracts_every_tag_in_order() -> None:
    caption = "Yangi buket 🌹 #Roza #ATIRGUL #tyulpan 150 000 so'm"
    assert extract_hashtags(caption) == ["roza", "atirgul", "tyulpan"]


def test_extraction_drops_numeric_tags() -> None:
    assert extract_hashtags("#roza #150000 #998901234567") == ["roza"]


def test_extraction_deduplicates_while_keeping_order() -> None:
    assert extract_hashtags("#roza #Roza #ROZA #lola") == ["roza", "lola"]


def test_extraction_of_a_caption_with_no_tags() -> None:
    assert extract_hashtags("Yangi buket, narxi kelishiladi") == []


def test_extraction_handles_an_empty_caption() -> None:
    assert extract_hashtags("") == []


def test_apostrophe_tags_are_extracted_as_one_key() -> None:
    assert extract_hashtags("#so'm #so’m #soʻm") == ["som"]
