"""Uzbek Latin -> Uzbek Cyrillic, for the template wording only (CP23).

The flower templates are written once, in Uzbek Latin, and their Cyrillic
variant is DERIVED here, so the two can never say different things. This is a
narrow tool for text the project itself wrote -- not for owner text, which is
never transliterated (see catalog/hashtags.py on why that is lossy).

The rules are the standard ones: digraphs first (sh, ch, o', g', yo, yu, ya,
ye), "e" is "э" at the start of a word and "е" elsewhere, a lone apostrophe
(ma'no) is the hard sign. Words whose Cyrillic spelling is not derivable --
Russian loans written with "ц" or a soft sign -- go in EXCEPTIONS.
"""

from __future__ import annotations

import re

APOSTROPHES = "'’‘ʼʻ`"

#: Whole words whose Cyrillic form the rules cannot produce, lower case.
EXCEPTIONS = {
    "alstromeriya": "альстромерия",
    "kompozitsiya": "композиция",
    "aksiya": "акция",
    "gortenziya": "гортензия",
    "8-mart": "8-Март",
}

_DIGRAPHS = (
    ("yo'", "йў"),
    ("o'", "ў"),
    ("g'", "ғ"),
    ("sh", "ш"),
    ("ch", "ч"),
    ("yo", "ё"),
    ("yu", "ю"),
    ("ya", "я"),
    ("ye", "е"),
)
_LETTERS = dict(
    zip(
        "abcdfghijklmnopqrstuvxyz",
        "абцдфгҳижклмнопқрстувхйз",
        strict=True,
    )
)
_VOWELS = set("aeiou")
_WORD = re.compile(r"[A-Za-z'’‘ʼʻ`\-0-9]+")


def _word(word: str) -> str:
    lower = word.lower()
    if lower in EXCEPTIONS:
        out = EXCEPTIONS[lower]
    else:
        for mark in APOSTROPHES[1:]:
            lower = lower.replace(mark, "'")
        out_chars: list[str] = []
        i = 0
        while i < len(lower):
            for latin, cyrillic in _DIGRAPHS:
                if lower.startswith(latin, i):
                    out_chars.append(cyrillic)
                    i += len(latin)
                    break
            else:
                char = lower[i]
                if char == "e":
                    first = i == 0 or not lower[i - 1].isalpha() or lower[i - 1] in _VOWELS
                    out_chars.append("э" if first else "е")
                elif char == "'":
                    out_chars.append("ъ")
                else:
                    out_chars.append(_LETTERS.get(char, char))
                i += 1
        out = "".join(out_chars)
    if word.isupper() and len(word) > 1:
        return out.upper()
    if word[:1].isupper():
        return out[:1].upper() + out[1:]
    return out


def to_cyrillic(text: str) -> str:
    """The Cyrillic spelling of project-written Uzbek Latin text."""
    return _WORD.sub(lambda match: _word(match.group(0)), text)
