"""Rendering helpers for outbound messages.

The bot's default parse_mode is HTML, so every piece of customer-supplied text
must be escaped on the way out. Doing it here rather than at storage time keeps
one escaped representation, at the only place it matters.
"""

from __future__ import annotations

import html

from gulbot.i18n import t
from gulbot.models.occasion import RecipientType


def escape(value: str) -> str:
    return html.escape(value, quote=False)


def addressed_label(label: str, recipient_type: str, lang: str) -> str:
    """The label as the bot should SAY it to the customer.

    Recipient presets are stored in the FIRST person, because that is how the
    customer picks them -- "Onam" means "my mother", and the button has to read
    that way. But the bot is not the customer's child. Rendering the stored
    word into a sentence the bot speaks makes it say "my mother", which is the
    grammar bug this exists to fix:

        Onam  ->  Onangiz          (mine -> yours)

    A CUSTOM label is returned UNCHANGED, on purpose. It is the customer's own
    words for their own person, and "Aziza singlim" already carries a
    first-person suffix that would have to be stripped and re-fitted under
    vowel harmony to convert -- on arbitrary free text that may be multi-word,
    a bare name, or not Uzbek at all. Echoing it verbatim is quoting the
    customer, which is correct; inflecting it wrongly is not. `render.py`
    instead reshapes the SENTENCE around a custom label so no possessive suffix
    is needed at all.

    Keyed on the recipient TYPE, never on the label text: renaming a preset to
    free text always sets the type to `custom` (see `rename_with_text`), so the
    two cannot drift apart, and matching on the string would convert a
    recipient renamed "Dilnoza" into "Opangiz".
    """
    if recipient_type == RecipientType.CUSTOM.value:
        return label
    return t(f"recipient.addr.{recipient_type}", lang)


def format_date(day: int, month: int, year: int | None) -> str:
    """Numeric form. Compact, used where space is tight."""
    base = f"{day:02d}.{month:02d}"
    return f"{base}.{year}" if year else base


def format_date_long(day: int, month: int, year: int | None, lang: str) -> str:
    """Warm form: "5-sentabr", the way a person writes a date in Uzbek.

    Russian stays numeric until CP15 rewrites that locale properly. Inventing
    half-polished Russian here would be worse than plainly correct digits --
    "5 сентября" needs the genitive month, which is a table this file has no
    business growing before someone reviews the tone of the rest of it.
    """
    if lang != "uz":
        return format_date(day, month, year)
    name = t(f"month.{month}", lang).lower()
    base = f"{day}-{name}"
    return f"{base} {year}" if year else base


def format_price(amount: int) -> str:
    """1200000 -> "1 200 000". A narrow no-break space would be typographically
    nicer and is a copy-paste hazard in a chat; a plain space is not."""
    return f"{amount:,}".replace(",", " ")
