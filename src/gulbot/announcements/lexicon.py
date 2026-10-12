"""Conservative Uzbek/Russian flower and colour matching, with source spans.

No general transliteration or description rewriting. Apostrophe normalization
is aligned with CP7 matching keys. Plain stdlib Levenshtein replaces rapidfuzz
for this small preparation lexicon; returned fuzzy matches ALWAYS need review.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from .numbers import is_number_token

_APOSTROPHES = "'’‘ʼʻ`´′＇"
_FOLD = str.maketrans("", "", _APOSTROPHES)
_WORD = re.compile(r"[^\W\d_]+(?:['’‘ʼʻ`´′＇][^\W\d_]+)*", re.UNICODE)
_SUFFIXES = (
    "larimiz",
    "laringiz",
    "larning",
    "lardan",
    "larni",
    "larda",
    "larga",
    "lari",
    "lar",
    "ingiz",
    "imiz",
    "ning",
    "dan",
    "ni",
    "ga",
    "da",
    "im",
)

# Original curated data; aliases cover the CP19 hashtag fixture's FLOWER rows.
# Occasion rows (birthday, wedding, 8mart) deliberately are not flower names.
FLOWERS = {
    "atirgul": ("roza", "роза", "розы", "rose", "roses", "атиргул", "gulatirgul"),
    "tyulpan": (
        "tulip",
        "tulips",
        "тюльпан",
        "тюльпаны",
        "лале",
        "lola gul",
        "тюлпан",
        "lola",
        "лола",
    ),
    "xrizantema": ("хризантема", "хризантемы", "chrysanthemum", "krizantema", "хризантема"),
    "chinnigul": ("гвоздика", "гвоздики", "carnation", "чиннигул"),
    "pion": ("пион", "пионы", "peony", "peonies"),
    "nilufar": ("лилия", "лилии", "lily", "нилуфар", "liliya"),
    "gerbera": ("гербера", "герберы"),
    "buket": ("букет", "bouquet", "guldasta", "гулдаста"),
    "eustoma": ("эустома", "эустомы", "lisianthus"),
    "gortenziya": ("гортензия", "гортензии", "hydrangea"),
    "orxideya": ("орхидея", "орхидеи", "orchid"),
    "gipsofila": ("гипсофила", "gypsophila"),
    "alstromeriya": ("альстромерия", "alstroemeria"),
    "frezia": ("фрезия", "freesia"),
    "ranunkulyus": ("ранункулюс", "ranunculus"),
    "lavanda": ("лаванда", "lavender"),
    "nargis": ("наргис", "нарцисс", "narcissus"),
    # CP23: the flower themes' own keys. "kust atirgul" is two words, so the
    # phrase matcher takes it before the single word "atirgul".
    "kustatirgul": (
        "kust atirgul",
        "кустовая роза",
        "кустовые розы",
        "куст атиргул",
        "spray rose",
        "spray roses",
    ),
    "mimoza": ("мимоза", "мимозы", "mimosa"),
}
COLOURS = {
    "qizil": ("қизил", "красный", "красная", "красные", "red"),
    "oq": ("оқ", "белый", "белая", "белые", "white"),
    "pushti": ("пушти", "розовый", "розовая", "розовые", "pink"),
    "sariq": ("сариқ", "желтый", "жёлтый", "желтая", "жёлтая", "yellow"),
    "kok": ("ko'k", "кўк", "синий", "синяя", "голубой", "blue"),
    "binafsha": ("бинафша", "фиолетовый", "фиолетовая", "purple"),
    "yashil": ("яшил", "зеленый", "зелёный", "green"),
    "qora": ("қора", "черный", "чёрный", "black"),
    "toqqizil": ("to'q qizil", "тўқ қизил", "бордовый", "burgundy"),
    "ochpushti": ("och pushti", "оч пушти", "светло розовый"),
    "krem": ("кремовый", "кремовая", "cream"),
    "shaftoli": ("шафтоли", "персиковый", "peach"),
    "aralash": ("аралаш", "разноцветный", "mix"),
}


def normalize_word(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold().translate(_FOLD)
    return " ".join(normalized.split())


@dataclass(frozen=True)
class LexiconMatch:
    source: str
    kind: str
    canonical: str | None
    confidence: str
    method: str
    alternatives: tuple[str, ...] = ()
    start: int = 0
    end: int = 0


def _distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        row = [i]
        for j, y in enumerate(b, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (x != y)))
        previous = row
    return previous[-1]


class LexiconMatcher:
    def __init__(
        self, shop_aliases: Mapping[str, str] | None = None, *, extra_flowers: Iterable[str] = ()
    ):
        self._entries: dict[str, set[tuple[str, str]]] = {}
        allowed = set(FLOWERS)
        for value in extra_flowers:
            key = normalize_word(value)
            if not key or not key.isalpha() or len(key) > 64:
                raise ValueError("invalid extra flower key")
            allowed.add(key)
            self._add(key, "flower", key)
        for kind, table in (("flower", FLOWERS), ("colour", COLOURS)):
            for canonical, aliases in table.items():
                self._add(canonical, kind, canonical)
                for alias in aliases:
                    self._add(alias, kind, canonical)
        if shop_aliases is not None and len(shop_aliases) > 2000:
            raise ValueError("alias list exceeds 2000 rows")
        for alias, canonical in (shop_aliases or {}).items():
            target = normalize_word(canonical)
            if target not in allowed:
                continue
            key = normalize_word(alias)
            if not key or len(key) > 64 or not all(w.isalpha() for w in key.split()):
                raise ValueError("invalid flower alias")
            if len(key.split()) > 4:
                raise ValueError("flower aliases must contain at most four words")
            self._add(key, "flower", target)
        self._max_phrase = min(4, max(len(k.split()) for k in self._entries))

    def _add(self, alias: str, kind: str, canonical: str) -> None:
        self._entries.setdefault(normalize_word(alias), set()).add((kind, canonical))

    @staticmethod
    def _result(source: str, entries: set[tuple[str, str]], method: str) -> LexiconMatch:
        ordered = sorted(entries)
        if len(ordered) > 1:
            kinds = {kind for kind, _ in entries}
            return LexiconMatch(
                source,
                next(iter(kinds)) if len(kinds) == 1 else "ambiguous",
                None,
                "low",
                "ambiguous",
                tuple(c for _, c in ordered),
                end=len(source),
            )
        kind, canonical = ordered[0]
        return LexiconMatch(
            source, kind, canonical, "low" if method == "fuzzy" else "high", method, end=len(source)
        )

    def match(self, text: str) -> LexiconMatch | None:
        if not isinstance(text, str) or len(text) > 64:
            raise ValueError("word/phrase exceeds 64 characters")
        key = normalize_word(text)
        if is_number_token(text):
            return None
        if key in self._entries:
            return self._result(text, self._entries[key], "exact")
        if not key or not key.isalpha():
            return None
        morphology: set[tuple[str, str]] = set()
        for suffix in _SUFFIXES:
            if key.endswith(suffix):
                morphology.update(self._entries.get(key[: -len(suffix)], set()))
        if morphology:
            return self._result(text, morphology, "morphology")
        if len(key) < 4:
            return None
        limit = 1 if len(key) < 7 else 2
        best = limit + 1
        candidates: set[tuple[str, str]] = set()
        for alias, entries in self._entries.items():
            if not alias.isalpha() or len(alias) < 4 or abs(len(alias) - len(key)) > limit:
                continue
            distance = _distance(key, alias)
            if distance > limit or 1 - distance / max(len(key), len(alias)) < 0.75:
                continue
            if distance < best:
                best, candidates = distance, set(entries)
            elif distance == best:
                candidates.update(entries)
        return self._result(text, candidates, "fuzzy") if candidates else None

    def find(self, text: str) -> list[LexiconMatch]:
        if not isinstance(text, str) or len(text) > 4096:
            raise ValueError("text exceeds 4096 characters")
        words, output, i = list(_WORD.finditer(text)), [], 0
        while i < len(words):
            found, used = None, 1
            for size in range(min(self._max_phrase, len(words) - i), 0, -1):
                start, end = words[i].start(), words[i + size - 1].end()
                if size > 1 and any(
                    not text[words[j].end() : words[j + 1].start()].isspace()
                    for j in range(i, i + size - 1)
                ):
                    continue
                source = text[start:end]
                if len(source) > 64:
                    continue
                candidate = self.match(source)
                if candidate is not None:
                    found, used = replace(candidate, start=start, end=end), size
                    break
            if found is not None:
                output.append(found)
            i += used
        return output
