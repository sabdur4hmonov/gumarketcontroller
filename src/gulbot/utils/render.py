"""Rendering helpers for outbound messages.

The bot's default parse_mode is HTML, so every piece of customer-supplied text
must be escaped on the way out. Doing it here rather than at storage time keeps
one escaped representation, at the only place it matters.
"""

from __future__ import annotations

import html

from gulbot.i18n import t


def escape(value: str) -> str:
    return html.escape(value, quote=False)


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
