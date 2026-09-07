"""Turning what a customer typed into a number a courier can dial.

Pure, and deliberately narrow. This is not a general phone library: it accepts
the shapes an Uzbek customer actually types and one explicit escape hatch for a
foreign number, and rejects everything else so the shop is never handed a string
that looks like a number and is not one.

WHY REJECTION MATTERS MORE THAN PERMISSIVENESS. A rejected number is a retry
prompt the customer sees immediately. An accepted-but-wrong number is discovered
by a courier standing outside the wrong building. When in doubt, refuse.
"""

from __future__ import annotations

import re

#: Uzbek numbers are +998 plus nine digits: a two-digit operator code and seven
#: more. Customers write the national part alone ("90 123 45 67") at least as
#: often as the full form, so both are accepted and normalised to one shape.
UZ_COUNTRY_CODE = "998"
UZ_NATIONAL_DIGITS = 9

#: E.164's own bounds, used only for a number the customer explicitly wrote with
#: a leading '+'. Without the '+' there is no way to tell a foreign number from
#: a mistyped local one, and guessing is how a courier gets a wrong number.
MIN_INTERNATIONAL_DIGITS = 10
MAX_INTERNATIONAL_DIGITS = 15

_DIGITS = re.compile(r"\d")


def normalize_phone(raw: str) -> str | None:
    """`+998901234567`, or None if this cannot be read as a number.

    >>> normalize_phone("90 123 45 67")
    '+998901234567'
    >>> normalize_phone("+998 (90) 123-45-67")
    '+998901234567'
    >>> normalize_phone("998901234567")
    '+998901234567'
    >>> normalize_phone("salom") is None
    True
    """
    text = raw.strip()
    if not text:
        return None
    explicitly_international = text.startswith("+")
    digits = "".join(_DIGITS.findall(text))
    if not digits:
        return None

    if len(digits) == UZ_NATIONAL_DIGITS:
        return f"+{UZ_COUNTRY_CODE}{digits}"

    if digits.startswith(UZ_COUNTRY_CODE) and len(digits) == len(UZ_COUNTRY_CODE) + (
        UZ_NATIONAL_DIGITS
    ):
        return f"+{digits}"

    # Anything else is only accepted when the customer said it was
    # international by writing the '+' themselves. A bare 11-digit string is far
    # more likely to be a typo in a local number than a foreign one.
    if explicitly_international and MIN_INTERNATIONAL_DIGITS <= len(digits) <= (
        MAX_INTERNATIONAL_DIGITS
    ):
        return f"+{digits}"

    return None


def normalize_shared_contact(phone_number: str) -> str | None:
    """The number Telegram hands over when the contact button is tapped.

    Telegram's own value is already a real number, but it arrives with and
    without a leading '+' depending on the client, so it is run through the same
    normaliser. A foreign number shared this way has no '+' to vouch for it, so
    it is accepted here on Telegram's authority rather than the customer's
    typing -- which is the whole difference between this and `normalize_phone`.
    """
    normalized = normalize_phone(phone_number)
    if normalized is not None:
        return normalized
    digits = "".join(_DIGITS.findall(phone_number))
    if MIN_INTERNATIONAL_DIGITS <= len(digits) <= MAX_INTERNATIONAL_DIGITS:
        return f"+{digits}"
    return None
