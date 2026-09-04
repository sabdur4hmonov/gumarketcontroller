"""The price parser matrix.

The adversarial cases lead, because they are the ones that cost money: a phone
number read as a price puts a wrong figure in front of a customer, and the shop
then has to honour it or argue about it.
"""

from __future__ import annotations

import pytest

from gulbot.catalog.prices import (
    MAX_PRICE_UZS,
    MIN_PRICE_UZS,
    PriceConfidence,
    mask_phone_numbers,
    parse_price,
)

# --- adversarial: phone numbers must never become prices -------------------

PHONE_CAPTIONS = [
    "Buyurtma uchun: +998 90 123 45 67",
    "Tel: +998901234567",
    "тел: 90 123 45 67",
    "Aloqa: 998 90 123 45 67",
    "Murojaat uchun 93-456-78-90",
    "Call +998 (90) 123-45-67",
    "Yangi buket 🌹 Telefon: 901234567",
    "@gulshop_uz  +998 71 200 30 40",
    "Buyurtma: 90 123 45 67 yoki 93 456 78 90",
]


@pytest.mark.parametrize("caption", PHONE_CAPTIONS)
def test_a_phone_number_is_never_read_as_a_price(caption: str) -> None:
    price, confidence = parse_price(caption)
    assert price is None, f"read {price} out of a phone number"
    assert confidence is PriceConfidence.NONE


@pytest.mark.parametrize("caption", PHONE_CAPTIONS)
def test_phone_masking_removes_the_digits_entirely(caption: str) -> None:
    masked = mask_phone_numbers(caption)
    assert not any(ch.isdigit() for ch in masked), masked


def test_a_price_and_a_phone_in_one_caption_yields_the_price() -> None:
    """The realistic caption: both appear, and only one is the price."""
    price, confidence = parse_price("Atirgul buketi 🌹 250 000 so'm. Buyurtma: +998 90 123 45 67")
    assert price == 250_000
    assert confidence is PriceConfidence.HIGH


def test_the_phone_cannot_win_when_it_comes_first() -> None:
    price, _ = parse_price("+998 90 123 45 67 — narx 180 000 so'm")
    assert price == 180_000


# --- adversarial: price by agreement ---------------------------------------


@pytest.mark.parametrize(
    "caption",
    [
        "narxi kelishiladi",
        "Narxi kelishiladi",
        "нархи келишилади",
        "Нархи келишилади",
        "Narx kelishiladi, murojaat qiling",
        "narxi kelishiladi 🌹",
    ],
)
def test_price_by_agreement_extracts_nothing(caption: str) -> None:
    """The price word is present, the number is not. That is not a price."""
    assert parse_price(caption) == (None, PriceConfidence.NONE)


@pytest.mark.parametrize(
    "caption",
    ["", "   ", "Yangi buket 🌹", "Atirgul", "#roza #atirgul", "Bugun ochiqmiz"],
)
def test_captions_with_no_number_at_all(caption: str) -> None:
    assert parse_price(caption) == (None, PriceConfidence.NONE)


# --- labelled amounts: HIGH ------------------------------------------------


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("150 000 so'm", 150_000),
        ("150 000 so’m", 150_000),
        ("150 000 soʻm", 150_000),
        ("150000 som", 150_000),
        ("150 000 сум", 150_000),
        ("150 000 сўм", 150_000),
        ("1 500 000 UZS", 1_500_000),
        ("1 500 000 uzs", 1_500_000),
        ("200,000 so'm", 200_000),
        ("200.000 so'm", 200_000),
        ("Atirgul buketi — 350 000 so'm", 350_000),
        ("narx 200000", 200_000),
        ("нарх 200000", 200_000),
        ("narxi 200 000", 200_000),
        ("нархи: 200 000", 200_000),
        ("Narx: 1 200 000 so'm", 1_200_000),
    ],
)
def test_labelled_amounts_are_high_confidence(caption: str, expected: int) -> None:
    price, confidence = parse_price(caption)
    assert price == expected
    assert confidence is PriceConfidence.HIGH


def test_k_with_a_currency_word_is_high() -> None:
    price, confidence = parse_price("150k so'm")
    assert price == 150_000
    assert confidence is PriceConfidence.HIGH


# --- unlabelled: MEDIUM ----------------------------------------------------


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("150.000", 150_000),
        ("150 000", 150_000),
        ("150000", 150_000),
        ("1 500 000", 1_500_000),
        ("Atirgul 25 ta — 450 000", 450_000),
    ],
)
def test_bare_plausible_numbers_are_medium(caption: str, expected: int) -> None:
    price, confidence = parse_price(caption)
    assert price == expected
    assert confidence is PriceConfidence.MEDIUM


@pytest.mark.parametrize(
    ("caption", "expected"),
    [("150k", 150_000), ("150K", 150_000), ("250 k", 250_000), ("1500k", 1_500_000)],
)
def test_the_k_shorthand_is_medium_without_a_currency_word(caption: str, expected: int) -> None:
    """ "k" states a magnitude, not a currency. Only a currency word is a label."""
    price, confidence = parse_price(caption)
    assert price == expected
    assert confidence is PriceConfidence.MEDIUM


# --- plausibility bounds ---------------------------------------------------


@pytest.mark.parametrize("caption", ["5 ta atirgul", "3 000", "2024 yil", "100", "12"])
def test_numbers_below_the_floor_are_not_prices(caption: str) -> None:
    """A stem count, a year, a small number. Not a bouquet price."""
    price, confidence = parse_price(caption)
    assert price is None
    assert confidence is PriceConfidence.NONE


def test_a_number_above_the_ceiling_is_not_a_price() -> None:
    price, _ = parse_price("99 999 999 999")
    assert price is None


def test_the_bounds_are_stated_and_sane() -> None:
    assert MIN_PRICE_UZS == 10_000
    assert MAX_PRICE_UZS == 50_000_000
    assert MIN_PRICE_UZS < MAX_PRICE_UZS


@pytest.mark.parametrize("value", [MIN_PRICE_UZS, MAX_PRICE_UZS])
def test_the_bounds_themselves_are_inclusive(value: int) -> None:
    price, _ = parse_price(f"{value} so'm")
    assert price == value


# --- realistic captions ----------------------------------------------------


def test_a_full_caption_with_tags_price_and_phone() -> None:
    caption = (
        "🌹 Yangi keldi! Atirgul buketi, 51 ta\n"
        "#atirgul #buket #sovga\n"
        "Narxi: 750 000 so'm\n"
        "Buyurtma: +998 90 123 45 67"
    )
    price, confidence = parse_price(caption)
    assert price == 750_000
    assert confidence is PriceConfidence.HIGH


def test_a_caption_where_only_the_stem_count_is_numeric() -> None:
    price, confidence = parse_price("Atirgul buketi, 51 ta. Narxi kelishiladi.")
    assert price is None
    assert confidence is PriceConfidence.NONE


def test_a_discount_percentage_is_not_a_price() -> None:
    price, _ = parse_price("Chegirma 20% 🌹")
    assert price is None


def test_the_first_labelled_amount_wins_over_a_later_bare_number() -> None:
    price, confidence = parse_price("Narx 300 000 so'm. 51 ta gul.")
    assert (price, confidence) == (300_000, PriceConfidence.HIGH)


def test_a_labelled_amount_beats_an_earlier_bare_number() -> None:
    """Labelled wins on confidence, not on position."""
    price, confidence = parse_price("51 ta atirgul, 300 000 so'm")
    assert (price, confidence) == (300_000, PriceConfidence.HIGH)


# --- shape -----------------------------------------------------------------


def test_confidence_is_a_named_level_not_a_number() -> None:
    """Three levels, so nobody averages two guesses or thresholds at 0.73."""
    assert {c.value for c in PriceConfidence} == {"high", "medium", "none"}


def test_none_confidence_always_comes_with_no_price() -> None:
    for caption in [*PHONE_CAPTIONS, "narxi kelishiladi", "", "5 ta"]:
        price, confidence = parse_price(caption)
        if confidence is PriceConfidence.NONE:
            assert price is None


def test_a_price_always_comes_with_a_confidence_above_none() -> None:
    for caption in ["150 000 so'm", "150000", "150k"]:
        price, confidence = parse_price(caption)
        assert price is not None
        assert confidence is not PriceConfidence.NONE
