"""Reviewable field extraction: ambiguity never silently becomes a price/count."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from gulbot.catalog.prices import MAX_PRICE_UZS, MIN_PRICE_UZS

from .correction import Corrector, default_corrector
from .learning import apply_learned
from .lexicon import COLOURS, FLOWERS, LexiconMatcher
from .numbers import find_numbers

PRICE_BEFORE = re.compile(r"(?:narx[іi]?|нарх[иі]?|цена)\s*[:=]?\s*$", re.I)
PRICE_AFTER = re.compile(r"^\s*(?:so['’ʻʼ]?m|сўм|сум|uzs)\b", re.I)
COUNT_AFTER = re.compile(r"^\s*(?:dona|ta|дона|та|штук|шт)\b", re.I)
NEGATED_AFTER = re.compile(r"^\s*(?:emas|эмас|bo['’ʻʼ]?lmasin|бўлмасин)\b", re.I)
NEGATED_BEFORE = re.compile(r"(?:^|\s)(?:ne|не)\s*$", re.I)


@dataclass
class Fields:
    flowers: list[str] = field(default_factory=list)
    count: int | None = None
    price: int | None = None
    colour: str = ""
    description: str = ""
    raw: str = ""
    warnings: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    #: CP23 addendum: the fields the owner should check first ("flowers",
    #: "colour", "price", "count"), what each flower/colour was heard as
    #: ([kind, source word, key, confidence]), and the shop's learned
    #: corrections applied before extraction ("heard → corrected").
    uncertain: list[str] = field(default_factory=list)
    heard: list[list[str]] = field(default_factory=list)
    learned: list[str] = field(default_factory=list)

    def data(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> Fields:
        return cls(**{key: value for key, value in data.items() if key in cls.__dataclass_fields__})

    def validate(self) -> None:
        if not self.flowers or len(self.flowers) > 8 or any(f not in FLOWERS for f in self.flowers):
            raise ValueError("Gul turini tanlang")
        if self.count is None or not 1 <= self.count <= 9999:
            raise ValueError("Soni 1–9999 bo'lishi kerak")
        if self.price is None or not MIN_PRICE_UZS <= self.price <= MAX_PRICE_UZS:
            raise ValueError("Narxi 10 000–50 000 000 so'm bo'lishi kerak")
        if self.colour not in COLOURS:
            raise ValueError("Rangini tanlang")
        if len(self.description) > 4096:
            raise ValueError("Tavsif juda uzun")


def extract(
    text: str,
    *,
    aliases: Mapping[str, str] | None = None,
    corrector: Corrector | None = None,
    learned: Mapping[str, str] | None = None,
) -> Fields:
    if not text.strip() or len(text) > 4096:
        raise ValueError("Tavsif 1–4096 belgi bo'lishi kerak")
    heard_text = text
    # CP23 addendum: the shop's learned corrections come BEFORE the general
    # lexicon; `raw` keeps exactly what was heard.
    text, applied = apply_learned(text, learned or {})
    if len(text) > 4096:
        raise ValueError("Tavsif 1–4096 belgi bo'lishi kerak")
    matcher = LexiconMatcher(aliases)
    domain = matcher.find(text)
    numbers = find_numbers(text)
    result = Fields(raw=heard_text, learned=applied)
    for match in domain:
        if NEGATED_AFTER.match(text[match.end :]) or NEGATED_BEFORE.search(
            text[max(0, match.start - 20) : match.start]
        ):
            result.warnings.append(f"Inkor qilingan gul/rang: {match.source} — tekshiring")
            continue
        if match.kind == "flower" and match.canonical and match.canonical not in result.flowers:
            result.flowers.append(match.canonical)
        elif match.kind == "colour" and match.canonical:
            if result.colour and result.colour != match.canonical:
                result.warnings.append("Ranglar bir nechta — tekshiring")
                result.uncertain.append("colour")
            else:
                result.colour = match.canonical
        if match.kind in {"flower", "colour"} and match.canonical:
            result.heard.append([match.kind, match.source, match.canonical, match.confidence])
        if match.confidence == "low":
            result.warnings.append(f"Gul/rang taxmini: {match.source}")
            result.uncertain.append("flowers" if match.kind == "flower" else "colour")
    prices: list[int] = []
    counts: list[int] = []
    for number in numbers:
        labelled_price = bool(
            PRICE_BEFORE.search(text[max(0, number.start - 20) : number.start])
            or PRICE_AFTER.match(text[number.end :])
        )
        if labelled_price and MIN_PRICE_UZS <= number.value <= MAX_PRICE_UZS:
            prices.append(number.value)
        elif (
            not labelled_price
            and 1 <= number.value <= 9999
            and (COUNT_AFTER.match(text[number.end :]) or number.source.endswith(("ta", "та")))
        ):
            counts.append(number.value)
    if len(prices) == 1:
        result.price = prices[0]
    else:
        plausible = [n.value for n in numbers if MIN_PRICE_UZS <= n.value <= MAX_PRICE_UZS]
        if not prices and len(plausible) == 1:
            result.price = plausible[0]
            result.warnings.append("Narx yorliqsiz — tekshiring")
        else:
            result.warnings.append("Narx aniqlanmadi yoki bir nechta")
        result.uncertain.append("price")
    if len(counts) == 1:
        result.count = counts[0]
    else:
        result.warnings.append("Gullar sonini kiriting")
        result.uncertain.append("count")
    corrected, changes = (corrector or default_corrector()).correct(
        text, protected=[(m.start, m.end) for m in domain] + [(n.start, n.end) for n in numbers]
    )
    # Keep the full description as typed (apart from shown corrections); no
    # fragment deletion can accidentally eat a delivery instruction or name.
    result.description = corrected
    result.corrections = [f"{c.source} → {c.replacement}" for c in changes]
    if not result.flowers:
        result.warnings.append("Gul turini tanlang")
        result.uncertain.append("flowers")
    if not result.colour:
        result.warnings.append("Rangini tanlang")
        result.uncertain.append("colour")
    result.uncertain = list(dict.fromkeys(result.uncertain))
    return result
