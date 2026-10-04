"""The taklifnoma's optional sections (CP17): the programme and the dress-code
colours.

PROGRAMME. The creator sends it as lines -- "18:00 Mehmonlarni kutib olish" --
and it is stored normalised in `share_pages.program`, one row per line:
"HH:MM item", or just "item" for a row without a time. normalise_program()
is the only way in (it refuses what it cannot read, rather than storing it
half-understood); program_rows() is the page's way out.

COLOURS. A fixed palette, picked from the bot -- never a colour the creator
types, so the page needs no inline style: each colour is a class in base.css
(.sw-<key>), and CSP stays `style-src 'self'`.
"""

from __future__ import annotations

import re
from typing import Final

#: At most this many programme rows, and this long an item.
PROGRAM_ROWS_MAX: Final = 8
PROGRAM_ITEM_MAX: Final = 44

#: At most this many dress-code colours.
COLORS_MAX: Final = 5

#: key -> (hex, names). The hex lives in base.css too (.sw-<key>); the test
#: suite checks the two agree.
DRESS_PALETTE: Final[dict[str, tuple[str, dict[str, str]]]] = {
    "oq": ("#ffffff", {"uz": "Oq", "ru": "Белый", "en": "White"}),
    "qora": ("#1d1d1f", {"uz": "Qora", "ru": "Чёрный", "en": "Black"}),
    "oltin": ("#c9a24a", {"uz": "Oltin", "ru": "Золотой", "en": "Gold"}),
    "kumush": ("#c0c2c9", {"uz": "Kumush", "ru": "Серебро", "en": "Silver"}),
    "bej": ("#e6d3b3", {"uz": "Bej", "ru": "Бежевый", "en": "Beige"}),
    "pushti": ("#f2b8c6", {"uz": "Pushti", "ru": "Розовый", "en": "Pink"}),
    "qizil": ("#b3202e", {"uz": "Qizil", "ru": "Красный", "en": "Red"}),
    "bordo": ("#6d1a2a", {"uz": "Bordo", "ru": "Бордовый", "en": "Burgundy"}),
    "lavanda": ("#b9a5d9", {"uz": "Lavanda", "ru": "Лавандовый", "en": "Lavender"}),
    "havorang": ("#a9cfee", {"uz": "Havorang", "ru": "Голубой", "en": "Sky blue"}),
    "kok": ("#2f5aa8", {"uz": "Ko'k", "ru": "Синий", "en": "Blue"}),
    "yashil": ("#3f7a4a", {"uz": "Yashil", "ru": "Зелёный", "en": "Green"}),
}

_TIMED = re.compile(r"^(\d{1,2})[:.](\d{2})\s*[-–—]?\s*(.*)$")
_STORED = re.compile(r"^(\d{2}:\d{2}) (.+)$")


class ProgramRefused(ValueError):
    """A programme that cannot be stored as written."""


def normalise_program(text: str) -> str:
    """The creator's lines as stored rows. Refuses more than PROGRAM_ROWS_MAX
    rows, an item over PROGRAM_ITEM_MAX, a time that is not a time, or a time
    with nothing after it."""
    rows: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        timed = _TIMED.match(line)
        if timed:
            hour, minute, item = int(timed[1]), int(timed[2]), timed[3].strip()
            if hour > 23 or minute > 59 or not item:
                raise ProgramRefused("time")
            row, item_text = f"{hour:02d}:{minute:02d} {item}", item
        else:
            row, item_text = line, line
        if len(item_text) > PROGRAM_ITEM_MAX:
            raise ProgramRefused("long")
        rows.append(row)
    if len(rows) > PROGRAM_ROWS_MAX:
        raise ProgramRefused("rows")
    return "\n".join(rows)


def program_rows(stored: str | None) -> list[tuple[str, str]]:
    """(time, item) per stored row; time is "" for a row without one."""
    rows: list[tuple[str, str]] = []
    for line in (stored or "").splitlines():
        if not line.strip():
            continue
        timed = _STORED.match(line)
        rows.append((timed[1], timed[2]) if timed else ("", line))
    return rows


def checked_colors(keys: object) -> str | None:
    """A tuple of palette keys as stored ("oq,oltin"), None for none. Refuses
    unknown keys, repeats and more than COLORS_MAX."""
    if keys is None:
        return None
    if not isinstance(keys, (tuple, list)) or not all(isinstance(k, str) for k in keys):
        raise ValueError("colours")
    if not keys:
        return None
    if len(keys) > COLORS_MAX or len(set(keys)) != len(keys):
        raise ValueError("colours")
    if any(k not in DRESS_PALETTE for k in keys):
        raise ValueError("colours")
    return ",".join(keys)


def colors_of(stored: str | None) -> list[str]:
    """Stored colours, known keys only (a palette change never breaks a page)."""
    return [k for k in (stored or "").split(",") if k in DRESS_PALETTE]
