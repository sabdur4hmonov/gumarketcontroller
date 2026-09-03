"""Rendering helpers for outbound messages.

The bot's default parse_mode is HTML, so every piece of customer-supplied text
must be escaped on the way out. Doing it here rather than at storage time keeps
one escaped representation, at the only place it matters.
"""

from __future__ import annotations

import html


def escape(value: str) -> str:
    return html.escape(value, quote=False)


def format_date(day: int, month: int, year: int | None) -> str:
    base = f"{day:02d}.{month:02d}"
    return f"{base}.{year}" if year else base
