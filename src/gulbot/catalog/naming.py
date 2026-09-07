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

THE ONE-LINE CAPTION, added after a real post arrived written as a single line.
"First line" is a good rule only when the florist used line breaks. Written as
one run --

    Nafis atirgul buketi 15 dona Narxi: 150 000 so'm #buket

-- the whole caption becomes the name, so every reminder and every order card
would carry 56 characters with the price stated twice. The admin guidance is
"one line per field", but guidance cannot be enforced on a shop typing into
Telegram, so a caption with no newline in it gets a tighter cut instead: stop
where the PRICE starts, since nothing after that is a name, and failing that
cap at a display length on a word boundary.

Deliberately narrow. A caption that DOES use line breaks is untouched, because
its first line is already the answer and second-guessing it would break the
common case to protect the rare one.
"""

from __future__ import annotations

import re
import unicodedata

from gulbot.catalog.prices import CURRENCY_WORDS, PRICE_WORDS

#: Matches products.name. Longer than any caption first line has any business
#: being, so the cap is a safety net rather than a routine truncation.
NAME_MAX_LENGTH = 200

#: A hashtag anywhere in the line. `\S+` rather than `\w+` because a tag may
#: carry an apostrophe (#gulbog'i) that normalize_hashtag strips later.
_HASHTAG = re.compile(r"#\S+")

_WHITESPACE_RUN = re.compile(r"[^\S\n]+")

#: Where price information starts in a run-on caption: a price word (Narxi:)
#: or a number followed by a currency word. Both vocabularies come from the
#: price parser rather than a second copy that would drift away from it.
#: The price WORD swallows the amount after it, so that a caption written the
#: other way round ("Narxi: 150 000 so'm atirgul buketi") leaves a clean name
#: behind rather than a name with the figure still stuck to its front.
_PRICE_START = re.compile(
    rf"(?:{PRICE_WORDS}\D{{0,12}}?\d[\d\s.,]*(?:\s*(?:k\b\s*)?{CURRENCY_WORDS})?"
    rf"|{PRICE_WORDS}"
    rf"|\d[\d\s.,]*\s*(?:k\b\s*)?{CURRENCY_WORDS}"
    rf"|\d[\d\s.,]*k\b)",
    re.IGNORECASE,
)

#: What a one-line caption is trimmed to when it carries no price marker.
#: Long enough for a real bouquet name, short enough to read in a reminder
#: caption and a browse list row.
SINGLE_LINE_MAX_LENGTH = 60

#: Trimmed from either end of a cut name. Separators a florist puts BETWEEN
#: fields, which become a dangling tail once the field after them is gone.
_EDGE_NOISE = " -–—:;,./|\\•"

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

    single_line = "\n" not in kept
    for line in kept.splitlines():
        without_tags = _HASHTAG.sub(" ", line)
        collapsed = _WHITESPACE_RUN.sub(" ", without_tags).strip()
        # A line that was only punctuation or emoji separators is not a name.
        if collapsed and any(ch.isalnum() for ch in collapsed):
            if single_line:
                collapsed = _trim_run_on(collapsed)
            return collapsed[:max_length].strip()
    return ""


def _trim_run_on(line: str) -> str:
    """Cut a caption written as one line down to a plausible name.

    Only reached when the caption had no line breaks at all -- see the module
    docstring. Returns the line unchanged when it is already short.
    """
    price_at = _PRICE_START.search(line)
    if price_at is not None:
        # Usually the price comes after the name, so the name is what precedes
        # it. A caption that OPENS with its price ("Narxi: 150 000 so'm atirgul
        # buketi") is the other way round, and the name is what FOLLOWS -- so
        # take whichever side actually has words in it.
        for candidate in (line[: price_at.start()], line[price_at.end() :]):
            trimmed = candidate.strip(_EDGE_NOISE)
            if trimmed and any(ch.isalnum() for ch in trimmed):
                return _cap(trimmed)

    return _cap(line)


def _cap(line: str) -> str:
    """Length-limit a single-line name on a word boundary."""
    if len(line) <= SINGLE_LINE_MAX_LENGTH:
        return line
    head = line[:SINGLE_LINE_MAX_LENGTH]
    return (head.rsplit(" ", 1)[0] if " " in head else head).strip()
