"""Strict Uzbek cardinal/amount parsing. Pure Python; no I/O or model imports.

parse_number parses a whole phrase or raises ValueError. find_numbers returns
integer candidates with ORIGINAL source offsets; it never chooses a price or
count without the later confirmation UI. No fuzzy correction of numeric words.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

MAX_TEXT = 4096
MAX_NUMBER = 10**12
_APOSTROPHES = "'’‘ʼʻ`´′＇"
_FOLD = str.maketrans("", "", _APOSTROPHES)
_UNITS = dict(
    zip(
        ["nol", "bir", "ikki", "uch", "tort", "besh", "olti", "yetti", "sakkiz", "toqqiz"],
        range(10),
        strict=False,
    )
)
_TENS = dict(
    zip(
        ["on", "yigirma", "ottiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "toqson"],
        range(10, 100, 10),
        strict=False,
    )
)
_CYR = dict(
    zip(
        [
            "нол",
            "бир",
            "икки",
            "уч",
            "тўрт",
            "беш",
            "олти",
            "етти",
            "саккиз",
            "тўққиз",
            "ўн",
            "йигирма",
            "ўттиз",
            "қирқ",
            "эллик",
            "олтмиш",
            "етмиш",
            "саксон",
            "тўқсон",
            "юз",
            "минг",
            "миллион",
            "миллиард",
            "ярим",
            "дона",
            "сўм",
            "сум",
        ],
        [
            "nol",
            "bir",
            "ikki",
            "uch",
            "tort",
            "besh",
            "olti",
            "yetti",
            "sakkiz",
            "toqqiz",
            "on",
            "yigirma",
            "ottiz",
            "qirq",
            "ellik",
            "oltmish",
            "yetmish",
            "sakson",
            "toqson",
            "yuz",
            "ming",
            "million",
            "milliard",
            "yarim",
            "dona",
            "som",
            "som",
        ],
        strict=False,
    )
)
_SCALES = {
    "ming": 1000,
    "million": 10**6,
    "milyon": 10**6,
    "mln": 10**6,
    "milliard": 10**9,
    "mlrd": 10**9,
}
_SMALL = {**_UNITS, **_TENS}
_ENDINGS = {"som", "uzs", "dona", "ta"}
_TOKEN = re.compile(
    r"\d+(?:[.,]\d+)*(?:/\d+(?:[.,]\d+)*)*(?:ta|та)?|[^\W\d_]+(?:['’‘ʼʻ`´′＇][^\W\d_]+)*",
    re.UNICODE,
)
_PHONE = re.compile(
    r"\+\d[\d\s()\-]{5,}\d|(?:tel|тел|aloqa|phone)\S*\s*:?\s*\d[\d\s()\-]{5,}\d", re.I
)
_UNLABELLED_PHONE = re.compile(r"(?<![\w.,])\d(?:[ \u00a0-]?\d){8,}(?![\w.,])")
_DATE = re.compile(r"\b\d{1,4}[/\-]\d{1,2}[/\-]\d{1,4}\b|\b\d{1,2}\.\d{1,2}\.\d{4}\b")


@dataclass(frozen=True)
class NumberMatch:
    value: int
    start: int
    end: int
    source: str


def _fold(word: str) -> str:
    key = unicodedata.normalize("NFKC", word).casefold().translate(_FOLD)
    if key in ("bitta", "бирта", "битта", "birta"):
        return "bir"
    if key.endswith(("ta", "та")):
        base = key[:-2]
        base = _CYR.get(base, base)
        if base in _SMALL or base.isdecimal():
            return base
    return _CYR.get(key, key)


def _literal(token: str) -> Decimal:
    if token in _SMALL:
        return Decimal(_SMALL[token])
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
        # Mixed grouping conventions are ambiguous, never silently strip both.
        if "." in token and "," in token:
            raise ValueError("mixed numeric separators")
        token = token.replace(",", "").replace(".", "")
    if not re.fullmatch(r"\d+(?:[.,]\d{1,6})?", token):
        raise ValueError("not an Uzbek cardinal")
    try:
        value = Decimal(token.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("invalid number") from exc
    if value > MAX_NUMBER:
        raise ValueError("number exceeds limit")
    return value


def _small(tokens: list[str]) -> Decimal:
    if len(tokens) == 1:
        return _literal(tokens[0])
    if len(tokens) == 2:
        a, b = map(_literal, tokens)
        if a in range(10, 100, 10) and 1 <= b <= 9 and b == int(b):
            return a + b
    raise ValueError("invalid cardinal order")


def _group(tokens: list[str]) -> Decimal:
    if not tokens:
        return Decimal(1)
    if tokens[-1] == "yarim":
        if len(tokens) == 1:
            return Decimal("0.5")
        whole = _group(tokens[:-1])
        if whole != int(whole):
            raise ValueError("fraction plus fraction")
        return whole + Decimal("0.5")
    if "yuz" not in tokens:
        return _small(tokens)
    if tokens.count("yuz") != 1:
        raise ValueError("repeated hundred")
    i = tokens.index("yuz")
    if i > 1:
        raise ValueError("invalid hundred multiplier")
    multiplier = _literal(tokens[0]) if i else Decimal(1)
    if multiplier != int(multiplier) or not 1 <= multiplier <= 9:
        raise ValueError("hundred multiplier must be 1..9")
    tail = _small(tokens[i + 1 :]) if tokens[i + 1 :] else Decimal(0)
    if tail != int(tail) or not 0 < tail < 100 and tokens[i + 1 :]:
        raise ValueError("invalid hundred remainder")
    return multiplier * 100 + tail


def parse_number(text: str) -> int:
    """Parse e.g. ellik bitta, тўрт юз эллик минг, 1,5 million.

    One terminal dona/ta or som/UZS is allowed. Decimal/fractional quantities
    must resolve to an integer after scaling. Reject signs, alternatives,
    arbitrary prose, repeated/ascending scales, and malformed grouping.
    """
    if not isinstance(text, str) or not text or len(text) > 256:
        raise ValueError("number phrase must contain 1..256 characters")
    raw = unicodedata.normalize("NFKC", text).strip().casefold()
    if not raw or re.search(r"[^\w\s.," + re.escape(_APOSTROPHES) + r"]", raw):
        raise ValueError("unsupported punctuation")
    raw = " ".join(raw.split())
    raw = re.sub(r"(?<!\S)\d{1,3}(?: \d{3})+(?!\S)", lambda m: m[0].replace(" ", ""), raw)
    tokens = [_fold(t) for t in raw.split()]
    if tokens and tokens[-1] in _ENDINGS:
        tokens.pop()
    if not tokens or len(tokens) > 64:
        raise ValueError("empty or too long number phrase")
    total, last_scale = Decimal(0), MAX_NUMBER + 1
    group: list[str] = []
    for token in tokens:
        if token in _SCALES:
            scale = _SCALES[token]
            if scale >= last_scale:
                raise ValueError("scales must strictly descend")
            subtotal = _group(group)
            if subtotal <= 0 or subtotal >= Decimal(last_scale) / scale:
                raise ValueError("invalid scale multiplier")
            total += subtotal * scale
            last_scale, group = scale, []
        else:
            group.append(token)
    if group:
        remainder = _group(group)
        if remainder >= last_scale:
            raise ValueError("remainder exceeds previous scale")
        total += remainder
    if not total.is_finite() or total != int(total) or not 0 <= total <= MAX_NUMBER:
        raise ValueError("expected a bounded integer")
    return int(total)


def _numeric(word: str) -> bool:
    key = _fold(word)
    return (
        key in _SMALL
        or key in _SCALES
        or key in {"yuz", "yarim"}
        or bool(re.fullmatch(r"\d+(?:[.,]\d+)*(?:/\d+(?:[.,]\d+)*)*", key))
    )


def is_number_token(text: str) -> bool:
    """Protect known numeral/counter/scale tokens from domain fuzzy matching."""
    return (
        isinstance(text, str)
        and 0 < len(text) <= 64
        and not any(ch.isspace() for ch in text)
        and _numeric(text)
    )


def find_numbers(text: str) -> list[NumberMatch]:
    """Locate contiguous numeric runs, masking phone/date-shaped text.

    Bad numeric runs are discarded in full, never retried as shorter numbers.
    Outputs are candidates; field assignment/conflict handling belongs to CP22.
    """
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise ValueError("text exceeds 4096 characters")
    masked = _DATE.sub(lambda m: " " * len(m[0]), text)
    masked = _PHONE.sub(lambda m: " " * len(m[0]), masked)
    masked = _UNLABELLED_PHONE.sub(lambda m: " " * len(m[0]), masked)
    matches = list(_TOKEN.finditer(masked))
    result, i = [], 0
    while i < len(matches):
        token = matches[i]
        # Ignore numeric fragments glued to other words (8mart, 1e6, id_123).
        if (token.start() > 0 and masked[token.start() - 1].isalnum()) or (
            token.end() < len(masked) and masked[token.end()].isalnum()
        ):
            i += 1
            continue
        if not _numeric(token[0]):
            i += 1
            continue
        j = i + 1
        while j < len(matches) and _numeric(matches[j][0]):
            gap = masked[matches[j - 1].end() : matches[j].start()]
            if not gap.isspace():
                break
            j += 1
        start, end = token.start(), matches[j - 1].end()
        # Reject signed literals rather than accidentally turning -450 into 450.
        signed = start > 0 and masked[start - 1] in "+-"
        try:
            value = parse_number(masked[start:end])
            if not signed and value < 10**9:
                result.append(NumberMatch(value, start, end, text[start:end]))
        except ValueError:
            pass
        i = j
    return result
