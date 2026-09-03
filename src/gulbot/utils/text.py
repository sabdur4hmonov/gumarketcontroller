"""Sanitising customer-supplied text.

Free-text labels are rendered into reminder messages months later, so they are
cleaned at ENTRY rather than at render: a bad string should never reach the
database in the first place.

Note the separate concern of HTML. The bot runs with parse_mode=HTML, so any
label is additionally escaped at render time (see render.py). Escaping is NOT
done here on purpose -- storing escaped text would corrupt lengths, break
comparisons, and double-escape as soon as it passes through twice.
"""

from __future__ import annotations

import re
import unicodedata

from gulbot.models.occasion import LABEL_MAX_LENGTH

# Control, format (zero-width joiners/marks), surrogate and private-use
# characters. These are invisible, survive copy-paste, and wreck rendering.
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co"})

_WHITESPACE_RUN = re.compile(r"\s+")


def sanitize_label(raw: str, *, max_length: int = LABEL_MAX_LENGTH) -> str:
    """Return a safe, capped, single-line label. May return "" if nothing remains."""
    # Order matters. Newlines and tabs are control characters that also SEPARATE
    # words, so they are turned into spaces first. Stripping them outright fuses
    # a two-line label into one run-on word.
    spaced = "".join(" " if ch.isspace() else ch for ch in raw)
    without_controls = "".join(
        ch for ch in spaced if unicodedata.category(ch) not in _STRIPPED_CATEGORIES
    )
    collapsed = _WHITESPACE_RUN.sub(" ", without_controls).strip()
    return collapsed[:max_length].strip()


def is_valid_label(value: str) -> bool:
    return bool(value)
