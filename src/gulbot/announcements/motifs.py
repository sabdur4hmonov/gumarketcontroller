"""Rasterise the CP23 line-art motifs (assets/motifs/*.svg) with Pillow.

The motifs are the project's own drawings (scripts/motifs_cp23.py writes
them), in a deliberately small SVG subset: <path> with M/L/H/V/C/S/Q/T/Z,
<circle>, <ellipse>, <line>, <g>, <title>, all stroked in "currentColor".
Anything outside it is REFUSED rather than drawn wrongly, so a hand edit that
uses an arc or a transform fails the motif test instead of a customer's post.

No new dependency: curves are flattened to polylines and drawn three times
over size, then downsampled -- that is the anti-aliasing. Results are cached
per (motif, size, colour): a server renders the same few dozen over and over,
and a cached motif costs a paste, not a redraw.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw

MOTIF_DIR = Path(__file__).with_name("assets") / "motifs"
VIEWBOX = 200.0
SUPERSAMPLE = 3
_NS = "{http://www.w3.org/2000/svg}"
_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "Z": 0}

Point = tuple[float, float]


class MotifError(ValueError):
    """An SVG outside the subset this renderer draws."""


@dataclass(frozen=True)
class Shape:
    subpaths: tuple[tuple[tuple[Point, ...], bool], ...]  # (points, closed)
    width: float
    fill: float  # 0 = none, else fill opacity


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, steps: int = 16) -> list[Point]:
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append(
            (
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return out


def _quad(p0: Point, p1: Point, p2: Point, steps: int = 12) -> list[Point]:
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append(
            (
                u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
            )
        )
    return out


def parse_path(d: str) -> list[tuple[list[Point], bool]]:
    """Path data -> flattened subpaths. Raises MotifError outside the subset."""
    tokens = _TOKEN.findall(d)
    if "".join(tokens).replace(" ", "") != re.sub(r"[\s,]+", "", d):
        raise MotifError("unsupported path data")
    subpaths: list[tuple[list[Point], bool]] = []
    current: list[Point] = []
    pos: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    last_control: Point | None = None
    last_command = ""
    i = 0
    command = ""
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
        elif not command:
            raise MotifError("path data must start with a command")
        upper = command.upper()
        if upper not in _ARGS:
            raise MotifError(f"unsupported path command {command}")
        count = _ARGS[upper]
        chunk = tokens[i : i + count]
        if len(chunk) != count or any(token.isalpha() for token in chunk):
            raise MotifError("truncated path command")
        args = [float(token) for token in chunk]
        i += count
        relative = command.islower()
        base = pos if relative else (0.0, 0.0)

        def absolute(index: int, values: list[float] = args, origin: Point = base) -> Point:
            return (origin[0] + values[index], origin[1] + values[index + 1])

        if upper == "M":
            if len(current) > 1:
                subpaths.append((current, False))
            pos = start = absolute(0)
            current = [pos]
            command = "l" if relative else "L"  # further pairs are line-tos
            last_control = None
        elif upper == "Z":
            if current:
                subpaths.append((current, True))
            current = [start]
            pos = start
            last_control = None
            command = ""  # Z takes no arguments: a number after it is an error
        elif upper in {"L", "H", "V"}:
            if upper == "H":
                target = (pos[0] + args[0], pos[1]) if relative else (args[0], pos[1])
            elif upper == "V":
                target = (pos[0], pos[1] + args[0]) if relative else (pos[0], args[0])
            else:
                target = absolute(0)
            current.append(target)
            pos, last_control = target, None
        elif upper in {"C", "S"}:
            if upper == "C":
                c1, c2, end = absolute(0), absolute(2), absolute(4)
            else:
                c1 = (
                    (2 * pos[0] - last_control[0], 2 * pos[1] - last_control[1])
                    if last_control and last_command in {"C", "S"}
                    else pos
                )
                c2, end = absolute(0), absolute(2)
            current.extend(_cubic(pos, c1, c2, end))
            pos, last_control = end, c2
        else:  # Q, T
            if upper == "Q":
                c, end = absolute(0), absolute(2)
            else:
                c = (
                    (2 * pos[0] - last_control[0], 2 * pos[1] - last_control[1])
                    if last_control and last_command in {"Q", "T"}
                    else pos
                )
                end = absolute(0)
            current.extend(_quad(pos, c, end))
            pos, last_control = end, c
        last_command = upper
    if len(current) > 1:
        subpaths.append((current, False))
    return subpaths


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> list[Point]:
    return [
        (cx + rx * math.cos(2 * math.pi * k / 48), cy + ry * math.sin(2 * math.pi * k / 48))
        for k in range(48)
    ]


def _number(element: ElementTree.Element, name: str) -> float:
    try:
        return float(element.attrib[name])
    except (KeyError, ValueError):
        raise MotifError(f"<{element.tag.removeprefix(_NS)}> needs a numeric {name}") from None


def _shapes(element: ElementTree.Element) -> list[Shape]:
    tag = element.tag.removeprefix(_NS)
    if tag in {"svg", "g"}:
        if "transform" in element.attrib:
            raise MotifError("transforms are not supported")
        return [shape for child in element for shape in _shapes(child)]
    if tag == "title":
        return []
    width = float(element.attrib.get("stroke-width", "3"))
    fill_value = element.attrib.get("fill", "none")
    if fill_value not in {"none", "currentColor"}:
        raise MotifError("fill must be none or currentColor")
    fill = float(element.attrib.get("fill-opacity", "1")) if fill_value == "currentColor" else 0.0
    if tag == "path":
        subpaths = parse_path(element.attrib.get("d", ""))
        shaped = tuple((tuple(points), closed) for points, closed in subpaths)
    elif tag == "circle":
        r = _number(element, "r")
        shaped = ((tuple(_ellipse(_number(element, "cx"), _number(element, "cy"), r, r)), True),)
    elif tag == "ellipse":
        points = _ellipse(
            _number(element, "cx"),
            _number(element, "cy"),
            _number(element, "rx"),
            _number(element, "ry"),
        )
        shaped = ((tuple(points), True),)
    elif tag == "line":
        shaped = (
            (
                (
                    (_number(element, "x1"), _number(element, "y1")),
                    (_number(element, "x2"), _number(element, "y2")),
                ),
                False,
            ),
        )
    else:
        raise MotifError(f"unsupported element <{tag}>")
    return [Shape(shaped, width, fill)]


@lru_cache(maxsize=64)
def load(name: str) -> tuple[Shape, ...]:
    """One motif's shapes, parsed once per process."""
    if not re.fullmatch(r"[a-z_]+", name):
        raise MotifError("bad motif name")
    root = ElementTree.parse(MOTIF_DIR / f"{name}.svg").getroot()
    if root.attrib.get("viewBox") != f"0 0 {VIEWBOX:g} {VIEWBOX:g}":
        raise MotifError("motifs use viewBox 0 0 200 200")
    return tuple(_shapes(root))


def motif_names() -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in MOTIF_DIR.glob("*.svg")))


@lru_cache(maxsize=512)
def raster(name: str, size: int, colour: str) -> Image.Image:
    """The motif as an RGBA square of `size` px in `colour`. Cached: do not mutate."""
    if not 8 <= size <= 2048:
        raise MotifError("motif size out of range")
    rgb = ImageColor.getrgb(colour)[:3]
    big = size * SUPERSAMPLE
    scale = big / VIEWBOX
    fills = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    strokes = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    fill_draw, stroke_draw = ImageDraw.Draw(fills), ImageDraw.Draw(strokes)
    for shape in load(name):
        width = max(1, round(shape.width * scale))
        for points, closed in shape.subpaths:
            scaled = [(x * scale, y * scale) for x, y in points]
            if shape.fill and closed and len(scaled) > 2:
                fill_draw.polygon(scaled, fill=(*rgb, round(255 * min(1.0, shape.fill))))
            line = [*scaled, scaled[0]] if closed else scaled
            stroke_draw.line(line, fill=(*rgb, 255), width=width, joint="curve")
            if not closed:
                radius = width / 2
                for x, y in (scaled[0], scaled[-1]):
                    stroke_draw.ellipse(
                        (x - radius, y - radius, x + radius, y + radius), fill=(*rgb, 255)
                    )
    fills.alpha_composite(strokes)
    return fills.resize((size, size), Image.Resampling.LANCZOS)
