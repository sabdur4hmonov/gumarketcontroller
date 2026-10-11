"""Conservative one-edit dictionary correction; no invented word frequencies.

The data is the separately licensed GPL-3.0 uz-hunspell source, unmodified.
Only a unique one-edit candidate replaces an unknown word. Domain and numeric
spans are protected; descriptions retain punctuation, whitespace and order.
Hunspell affix rules are preserved as source, not claimed to be implemented here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .lexicon import normalize_word
from .numbers import is_number_token

ASSETS = Path(__file__).with_name("assets")
WORD = re.compile(r"[^\W\d_]+(?:['’‘ʼʻ`´′＇][^\W\d_]+)*", re.UNICODE)
REFERENCE = re.compile(r"(?:https?://|www\.)[^\s]+|[\w.+-]+@[\w.-]+|(?<!\w)[@#][\w'’ʻʼ]+", re.I)
APOSTROPHES = str.maketrans({ch: "'" for ch in "’‘ʼʻ`´′＇"})
ALPHABETS = ("abcdefghijklmnopqrstuvwxyz'", "абвгдеёжзийклмнопрстуфхцчшъыьэюяўқғҳ")


@dataclass(frozen=True)
class Correction:
    source: str
    replacement: str
    start: int
    end: int


class Corrector:
    def __init__(self, words: list[str]) -> None:
        self.words: dict[str, str] = {}
        for word in words:
            key = normalize_word(word)
            if key.isalpha():
                self.words.setdefault(key, word.translate(APOSTROPHES).lower())

    def candidates(self, word: str) -> list[str]:
        key = normalize_word(word)
        if key in self.words or not 4 <= len(key) <= 24 or not key.isalpha():
            return []
        alphabet = ALPHABETS[int(any("а" <= ch <= "я" or ch in "ўқғҳ" for ch in key))]
        splits = [(key[:i], key[i:]) for i in range(len(key) + 1)]
        edits = {a + b[1:] for a, b in splits if b}
        edits.update(a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1)
        edits.update(a + ch + b[1:] for a, b in splits if b for ch in alphabet)
        edits.update(a + ch + b for a, b in splits for ch in alphabet)
        return sorted({self.words[e] for e in edits if e in self.words})[:6]

    def correct(
        self, text: str, *, protected: list[tuple[int, int]]
    ) -> tuple[str, list[Correction]]:
        if len(text) > 4096:
            raise ValueError("description exceeds 4096 characters")
        protected = [*protected, *(match.span() for match in REFERENCE.finditer(text))]
        changes: list[Correction] = []
        for match in list(WORD.finditer(text))[:100]:
            start, end = match.span()
            if any(start < right and end > left for left, right in protected):
                continue
            word = match.group()
            if is_number_token(word) or word[:1].isupper():
                continue  # Proper names are owner's words, too.
            candidates = self.candidates(word)
            if len(candidates) == 1:
                changes.append(Correction(word, candidates[0], start, end))
        output = text
        for change in reversed(changes):
            output = output[: change.start] + change.replacement + output[change.end :]
        return output.translate(APOSTROPHES), changes


@lru_cache(maxsize=1)
def default_corrector() -> Corrector:
    words: list[str] = []
    for name in ("uz_UZ.dic", "uz_UZ_Cyrl.dic"):
        try:
            lines = (ASSETS / "dictionary" / name).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue  # Missing spelling data must not disable domain/text entry.
        words.extend(line.split("/", 1)[0] for line in lines[1:])
    return Corrector(words)
