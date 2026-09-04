"""Deriving a product name from a shop caption.

Pure, like the rest of `gulbot.catalog` -- no database, no Telegram, no
settings. tests/test_catalog_purity.py fails the build if that stops being true.

WHY THIS EXISTS: `products.name` is NOT NULL, and a channel post has no name
field. The florist writes something like

    Qizil atirgul buketi 51 ta
    Narxi: 450 000 so'm
    #atirgul #buket

and the useful name is the first line. Hashtags are stripped because they are
already stored, indexed and searchable in `product_hashtags`; repeating them in
the display name would just make every card noisy.

It may return "". An album member that arrives before the caption-bearing one
has no caption at all, and there is nothing to invent from. The indexer treats
"" as provisional and the finalize step, which runs only once a caption has
been seen, replaces it.
"""

from __future__ import annotations

import re
import unicodedata

#: Matches products.name. Longer than any caption first line has any business
#: being, so the cap is a safety net rather than a routine truncation.
NAME_MAX_LENGTH = 200

#: A hashtag anywhere in the line. `\S+` rather than `\w+` because a tag may
#: carry an apostrophe (#gulbog'i) that normalize_hashtag strips later.
_HASHTAG = re.compile(r"#\S+")

_WHITESPACE_RUN = re.compile(r"[^\S\n]+")

# Invisible characters that survive copy-paste and wreck rendering. Same set
# as utils.text, which cannot be reused here: it imports the ORM layer, and
# this module is part of the pure catalogue.
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co"})


def product_name(caption: str | None, *, max_length: int = NAME_MAX_LENGTH) -> str:
    """The first meaningful line of a caption, without its hashtags.

    Returns "" when the caption is missing, blank, or made of nothing but
    hashtags -- a legitimate post shape ("#atirgul #buket" and a photo), and
    the caller decides what to show instead.
    """
    if not caption:
        return ""

    # ORDER MATTERS, and getting it wrong is exactly the bug CP3's label
    # sanitiser had. A tab is BOTH a separator and a control character, so
    # stripping controls first fuses "Bahor<TAB>buketi" into one run-on word.
    # Separators become spaces first; only then do the invisibles go. Newlines
    # survive both steps -- they are what separates the name from the price
    # line under it.
    spaced = "".join(" " if (ch.isspace() and ch != "\n") else ch for ch in caption)
    kept = "".join(
        ch for ch in spaced if ch == "\n" or unicodedata.category(ch) not in _STRIPPED_CATEGORIES
    )

    for line in kept.splitlines():
        without_tags = _HASHTAG.sub(" ", line)
        collapsed = _WHITESPACE_RUN.sub(" ", without_tags).strip()
        # A line that was only punctuation or emoji separators is not a name.
        if collapsed and any(ch.isalnum() for ch in collapsed):
            return collapsed[:max_length].strip()
    return ""
