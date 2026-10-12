"""Learning from the owner's corrections, per shop (CP23 addendum). Pure.

When an owner fixes what speech recognition got wrong, the bot remembers the
mishearing -- "heard" -> "corrected" -- and applies it before the general
lexicon next time, for THAT shop only (services/announcement_learning.py
stores it; nothing here touches a database).

What is learned, and what is never learned:

  * only SHORT, token-level fixes: at most three words and 40 characters on
    each side. A rewritten description is never stored -- its replaced spans
    are too long to qualify;
  * only a MISHEARING: the heard words must NOT already be a flower, a colour
    or a number the bot understands. Replacing "atirgul" with "lola" is a
    change of mind, not a mishearing; learning it would turn every future
    rose into a tulip;
  * the correction must be something the bot understands: a flower or colour
    of the lexicon, or a number phrase (a price pattern).

A flower or colour changed with the buttons teaches only when the word it
replaces was a GUESS (a fuzzy, low-confidence match) -- the guess was wrong,
and the word that misled it is what is remembered.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping
from dataclasses import dataclass

from .lexicon import LexiconMatcher, normalize_word
from .numbers import parse_number

MAX_WORDS = 3
MAX_CHARS = 40
_WORD = re.compile(r"[^\W_]+(?:['’‘ʼʻ`][^\W_]+)*", re.UNICODE)


@dataclass(frozen=True)
class Learned:
    heard: str  # normalised (lower case, apostrophes folded)
    corrected: str  # as the owner typed it, or a lexicon key
    kind: str  # flower | colour | number


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(normalize_word(m.group(0)), m.start(), m.end()) for m in _WORD.finditer(text)]


def apply_learned(text: str, learned: Mapping[str, str]) -> tuple[str, list[str]]:
    """`text` with every learned heard phrase replaced, whole words only.

    Returns the new text and what was applied ("heard → corrected"), so the
    owner sees it beside the result. Longer phrases are tried first.
    """
    if not learned:
        return text, []
    phrases = sorted(
        ((tuple(heard.split()), corrected) for heard, corrected in learned.items()),
        key=lambda pair: -len(pair[0]),
    )
    tokens = _tokens(text)
    out: list[str] = []
    applied: list[str] = []
    cursor = 0
    i = 0
    while i < len(tokens):
        for words, corrected in phrases:
            size = len(words)
            if tuple(t[0] for t in tokens[i : i + size]) == words:
                start, end = tokens[i][1], tokens[i + size - 1][2]
                out.append(text[cursor:start])
                out.append(corrected)
                applied.append(f"{text[start:end]} → {corrected}")
                cursor, i = end, i + size
                break
        else:
            i += 1
    out.append(text[cursor:])
    return "".join(out), applied


def _understood(matcher: LexiconMatcher, phrase: str) -> tuple[str, str] | None:
    """(kind, key) when the phrase is a flower or colour the bot knows for sure."""
    if len(phrase) > 64:
        return None
    match = matcher.match(phrase)
    if match is None or match.canonical is None or match.confidence != "high":
        return None
    if match.kind not in {"flower", "colour"}:
        return None
    return match.kind, match.canonical


def _is_number(phrase: str) -> bool:
    try:
        parse_number(phrase)
    except ValueError:
        return False
    return True


def _short(phrase: str) -> bool:
    return 0 < len(phrase.split()) <= MAX_WORDS and len(phrase) <= MAX_CHARS


def classify(heard: str, corrected: str, matcher: LexiconMatcher | None = None) -> Learned | None:
    """One replaced span -> a correction worth learning, or None."""
    matcher = matcher or LexiconMatcher()
    heard_key, corrected = normalize_word(heard), " ".join(corrected.split())
    if not (_short(heard_key) and _short(corrected)) or heard_key == normalize_word(corrected):
        return None
    if _understood(matcher, heard) is not None or _is_number(heard):
        return None  # the bot understood those words: a change of mind
    target = _understood(matcher, corrected)
    if target is not None:
        return Learned(heard_key, corrected, target[0])
    if _is_number(corrected):
        return Learned(heard_key, corrected, "number")
    return None


def diff_corrections(heard_text: str, corrected_text: str) -> list[Learned]:
    """What a re-typed text teaches: its short, replaced, understood spans."""
    before, after = _tokens(heard_text), _tokens(corrected_text)
    matcher = LexiconMatcher()
    found: list[Learned] = []
    opcodes = difflib.SequenceMatcher(
        a=[t[0] for t in before], b=[t[0] for t in after], autojunk=False
    ).get_opcodes()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag != "replace" or i2 - i1 > MAX_WORDS or j2 - j1 > MAX_WORDS:
            continue
        heard = heard_text[before[i1][1] : before[i2 - 1][2]]
        corrected = corrected_text[after[j1][1] : after[j2 - 1][2]]
        learned = classify(heard, corrected, matcher)
        if learned is not None and learned not in found:
            found.append(learned)
    return found


def from_button(heard: list[list[str]], kind: str, removed: str, added: str) -> Learned | None:
    """A flower or colour changed by button: learn only a wrong GUESS.

    `heard` is Fields.heard -- [kind, source word, key, confidence] per match.
    """
    guesses = [
        entry
        for entry in heard
        if len(entry) == 4 and entry[0] == kind and entry[2] == removed and entry[3] == "low"
    ]
    if len(guesses) != 1 or not added:
        return None
    source = guesses[0][1]
    if not _short(normalize_word(source)):
        return None
    return Learned(normalize_word(source), added, kind)
