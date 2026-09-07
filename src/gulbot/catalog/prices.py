"""Extracting a price from a shop caption.

Pure. No database, no Telegram, no settings.

THE HEURISTIC, and why it lands where it does
---------------------------------------------
Captions are written by a florist, not a data entry clerk. They contain prices,
phone numbers, bouquet sizes, discount percentages and emoji, in any order. The
parser's job is not to be clever; it is to be RIGHT when it is confident and
to say nothing when it is not, because a wrong price shown to a customer is
worse than no price at all -- the shop has to honour it or argue about it.

Order of operations:

1. MASK PHONE NUMBERS FIRST. This is the single most important step. Uzbek
   mobile numbers ("+998 90 123 45 67", "тел: 901234567") are long digit runs
   with separators, which is exactly what a thousands-separated price looks
   like. Masking them before looking for prices is the only reliable way to
   stop "call us on 90 123 45 67" becoming a 901,234,567 so'm bouquet.

2. LOOK FOR A LABELLED AMOUNT -> confidence HIGH. Labelled means a currency
   word after the number (so'm / сум / сўм / UZS) or a price word before it
   (narx / narxi / нарх / нархи). The label is what makes it a price rather
   than a number that happens to be nearby.

3. FAILING THAT, LOOK FOR A BARE PLAUSIBLE NUMBER -> confidence MEDIUM. A
   number in a believable price range with no label. Probably the price;
   possibly a stem count or an Instagram handle. Shown with a caveat by CP9,
   never treated as authoritative.

4. OTHERWISE -> NONE. "Narxi kelishiladi" (price by agreement) lands here, and
   so does any caption whose only digits were a phone number.

`150k` is treated as 150000 but stays MEDIUM: "k" is a magnitude marker, not a
currency marker, and the brief defines high confidence as a currency or price
label. A caption reading "150k so'm" gets both, and so gets HIGH.

PLAUSIBILITY BOUNDS exist because an unbounded parser turns any stray number
into a price. A bouquet under 10,000 so'm or over 50,000,000 is not a bouquet
price; it is a year, a stem count, a follower count or a typo.
"""

from __future__ import annotations

import re
from enum import StrEnum


class PriceConfidence(StrEnum):
    """Deliberately three named levels, not a float.

    A float invites arithmetic that means nothing -- averaging two guesses, or
    thresholding at 0.73 because it looked about right on a Tuesday. Three
    levels force the caller to decide what each one means.
    """

    HIGH = "high"
    MEDIUM = "medium"
    NONE = "none"


#: A bouquet costs somewhere in here. Outside it, the number is something else.
MIN_PRICE_UZS = 10_000
MAX_PRICE_UZS = 50_000_000

#: Currency words, Latin and Cyrillic, with every apostrophe variant allowed
#: inside so'm.
#: Public because `naming.py` reuses both of these to find where a name stops
#: and price information begins. One vocabulary, not two that drift apart.
CURRENCY_WORDS = r"(?:so[’'‘ʼʻ`´]?m|s[oў]m|сум|сўм|uzs|у\.?е\.?)"

#: Price words that can precede an amount.
PRICE_WORDS = r"(?:narx(?:i)?|нарх(?:и)?|цена|price)"

_SEPARATORS = "  .,'’"

#: A run that COULD be a phone number. Whether it actually is one is decided by
#: counting digits, not characters -- "1 500 000" is nine characters of digits
#: and separators, and masking it as a phone would eat a legitimate price.
_PHONE_CANDIDATE_RE = re.compile(r"\+?\d[\d\s\-()]{5,}\d")

#: Uzbek numbers are 9 digits nationally, 12 with the country code. The largest
#: plausible price, 50 000 000, is 8. That gap is the whole discriminator.
PHONE_MIN_DIGITS = 9

#: An explicit phone lead-in, even when the number that follows is short.
_PHONE_LABEL_RE = re.compile(
    r"(?:tel|тел|phone|aloqa|murojaat|call)\S*\s*:?\s*\+?[\d\s\-()]{6,}",
    re.IGNORECASE,
)

_NUMBER = r"\d[\d\s .,]*\d|\d"

_LABELLED_SUFFIX_RE = re.compile(rf"({_NUMBER})\s*(?:k\b\s*)?{CURRENCY_WORDS}", re.IGNORECASE)
_LABELLED_PREFIX_RE = re.compile(rf"{PRICE_WORDS}\D{{0,12}}?({_NUMBER})", re.IGNORECASE)
_K_FORM_RE = re.compile(rf"({_NUMBER})\s*k\b", re.IGNORECASE)
_BARE_RE = re.compile(rf"({_NUMBER})")


def _to_int(raw: str, *, thousands_k: bool = False) -> int | None:
    """Turn "1 500 000" or "150.000" into an int.

    Every separator is treated the same way. Uzbek captions use spaces, dots
    and commas interchangeably for thousands, and decimal so'm does not exist
    in practice -- nobody prices a bouquet at 150.50.
    """
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    value = int(digits)
    if thousands_k:
        value *= 1000
    return value


def _plausible(value: int | None) -> bool:
    return value is not None and MIN_PRICE_UZS <= value <= MAX_PRICE_UZS


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def _blank_if_phone(match: re.Match[str]) -> str:
    """Mask only runs with enough digits to be a phone number.

    A leading + is decisive on its own: nobody writes a price that way.
    """
    run = match.group(0)
    digits = sum(ch.isdigit() for ch in run)
    if run.lstrip().startswith("+") or digits >= PHONE_MIN_DIGITS:
        return " " * len(run)
    return run


def mask_phone_numbers(caption: str) -> str:
    """Blank out anything phone-shaped, so price hunting cannot see it."""
    masked = _PHONE_LABEL_RE.sub(_blank, caption)
    return _PHONE_CANDIDATE_RE.sub(_blank_if_phone, masked)


def parse_price(caption: str) -> tuple[int | None, PriceConfidence]:
    """Return (price in so'm, confidence). See the module docstring."""
    if not caption:
        return None, PriceConfidence.NONE

    text = mask_phone_numbers(caption)

    # 1. labelled: a currency word after the number
    for match in _LABELLED_SUFFIX_RE.finditer(text):
        is_k = bool(re.search(r"\d\s*k\b", match.group(0), re.IGNORECASE))
        value = _to_int(match.group(1), thousands_k=is_k)
        if _plausible(value):
            return value, PriceConfidence.HIGH

    # 2. labelled: a price word before the number
    for match in _LABELLED_PREFIX_RE.finditer(text):
        value = _to_int(match.group(1))
        if _plausible(value):
            return value, PriceConfidence.HIGH
        # "narx 150k"
        tail = text[match.end() : match.end() + 2]
        if tail.strip().lower().startswith("k"):
            boosted = _to_int(match.group(1), thousands_k=True)
            if _plausible(boosted):
                return boosted, PriceConfidence.HIGH

    # 3. the k shorthand, unlabelled
    for match in _K_FORM_RE.finditer(text):
        value = _to_int(match.group(1), thousands_k=True)
        if _plausible(value):
            return value, PriceConfidence.MEDIUM

    # 4. a bare plausible number
    for match in _BARE_RE.finditer(text):
        value = _to_int(match.group(1))
        if _plausible(value):
            return value, PriceConfidence.MEDIUM

    return None, PriceConfidence.NONE
