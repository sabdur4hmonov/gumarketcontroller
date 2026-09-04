"""Normalising hashtags from shop captions.

Pure. No database, no Telegram, no settings -- tests/test_catalog_purity.py
fails the build if that stops being true.

WHAT THIS DOES NOT DO: transliterate. "роза" is not turned into "roza" here.
Cross-script synonyms are handled by the `hashtag_aliases` table instead, which
maps роза -> atirgul and rose -> atirgul as data. Two reasons:

  * transliteration is lossy in both directions between Uzbek Latin and Uzbek
    Cyrillic (o' / ў, g' / ғ, sh / ш), so a transliterating normaliser would
    quietly merge words that are not the same word;
  * an alias row is inspectable and editable by whoever runs the shop. A
    transliteration table buried in code is neither.

ON HOMOGLYPHS: the brief asks whether real captions mix scripts INSIDE one
word -- Latin "a" inside an otherwise Cyrillic word, and so on. There is no
corpus to check against yet: nothing is indexed until CP8. So this deliberately
does NOT build homoglyph detection. The likely real failure is a shop typing
consistently in one script per post, which the alias table already covers.
CP8 should collect real captions and revisit this with evidence.
"""

from __future__ import annotations

import re
import unicodedata

#: Every apostrophe-ish character seen in Uzbek text. U+02BB and U+02BC are the
#: technically correct ones for oʻ and gʻ; the rest are what people actually
#: type. All are REMOVED, so so'm / so'm / soʼm / so`m collapse to "som".
APOSTROPHES = "'’‘ʼʻ`´′＇"

_APOSTROPHE_RE = re.compile(f"[{re.escape(APOSTROPHES)}]")

#: What survives normalisation: letters, digits, underscore. Anything else --
#: punctuation, emoji, zero-width marks -- is dropped.
_KEEP = re.compile(r"[^\w]", re.UNICODE)

_LEADING_HASHES = re.compile(r"^#+")


def normalize_hashtag(raw: str) -> str:
    """Reduce a raw hashtag to its matching key. May return "".

    An empty return means "this is not a usable hashtag" and callers should
    drop it rather than store it.

    Digit-only tokens return "" on purpose. `#150000` is a price and
    `#998901234567` is a phone number; neither is a product tag, and letting
    them through would put numbers into the same keyspace as flower names.
    """
    if not raw:
        return ""

    # NFKC first: it folds full-width and compatibility forms into the plain
    # characters the rest of this function expects.
    text = unicodedata.normalize("NFKC", raw).strip()
    text = _LEADING_HASHES.sub("", text)
    text = _APOSTROPHE_RE.sub("", text)
    text = text.casefold()
    text = _KEEP.sub("", text)

    if not text:
        return ""
    # A tag with no letter at all carries no meaning we can match on.
    if not any(ch.isalpha() for ch in text):
        return ""
    return text


def extract_hashtags(caption: str) -> list[str]:
    """Every normalised hashtag in a caption, in order, without duplicates.

    Order is preserved because the first recognised tag is the most likely
    subject of the post; CP9 may want that when ranking.
    """
    seen: dict[str, None] = {}
    for match in re.finditer(r"#\S+", caption or ""):
        normalized = normalize_hashtag(match.group(0))
        if normalized:
            seen.setdefault(normalized, None)
    return list(seen)
