"""Draw the CP23 flower motifs: original line art, written out as SVG.

    python scripts/motifs_cp23.py          # (re)writes src/gulbot/announcements/assets/motifs/

Every motif is geometry in this file -- spirals, petals, leaves, stems --
drawn for this project; no stock image or third-party artwork is traced or
copied. The output is plain SVG in the subset `gulbot.announcements.motifs`
rasterises (path M/L/C/Q/Z, circle, ellipse, line; stroke="currentColor").
tests/test_flower_motifs.py regenerates them and fails if a committed file
differs, so the SVGs and this source can never disagree.
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/gulbot/announcements/assets/motifs"
SIZE = 200


def f(value: float) -> str:
    text = f"{value:.1f}"
    return "0" if text in {"-0.0", "0.0"} else text.removesuffix(".0")


def pt(x: float, y: float) -> str:
    return f"{f(x)} {f(y)}"


def polar(cx: float, cy: float, r: float, degrees: float) -> tuple[float, float]:
    a = math.radians(degrees)
    return cx + r * math.cos(a), cy + r * math.sin(a)


class Drawing:
    def __init__(self) -> None:
        self.items: list[str] = []

    def path(self, d: str, width: float = 3, fill: bool = False) -> None:
        extra = ' fill="currentColor" fill-opacity="0.18"' if fill else ' fill="none"'
        self.items.append(f'<path d="{d}" stroke-width="{f(width)}"{extra}/>')

    def circle(self, cx: float, cy: float, r: float, width: float = 3, fill: bool = False) -> None:
        extra = ' fill="currentColor"' if fill else ' fill="none"'
        self.items.append(
            f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}" stroke-width="{f(width)}"{extra}/>'
        )

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, width: float = 3) -> None:
        self.items.append(
            f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(rx)}" ry="{f(ry)}" '
            f'stroke-width="{f(width)}" fill="none"/>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 3) -> None:
        self.items.append(
            f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" stroke-width="{f(width)}"/>'
        )

    def svg(self, title: str) -> str:
        body = "\n  ".join(self.items)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" '
            'stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">\n'
            f"  <title>{title} (original line art, gulbot CP23)</title>\n  {body}\n</svg>\n"
        )


# --- shapes ------------------------------------------------------------------


def petal(
    cx: float, cy: float, degrees: float, length: float, width: float, tip: float = 0.6
) -> str:
    """A pointed petal or leaf from its base, as two cubic curves."""
    a = math.radians(degrees)
    dx, dy = math.cos(a), math.sin(a)
    nx, ny = -dy, dx
    tx, ty = cx + dx * length, cy + dy * length

    def at(along: float, across: float) -> str:
        return pt(cx + dx * length * along + nx * across, cy + dy * length * along + ny * across)

    return (
        f"M {pt(cx, cy)} C {at(0.3, width)} {at(0.85, width * tip)} {pt(tx, ty)} "
        f"C {at(0.85, -width * tip)} {at(0.3, -width)} {pt(cx, cy)} Z"
    )


def round_petal(cx: float, cy: float, degrees: float, length: float, width: float) -> str:
    """A petal with a rounded tip (gerbera, orchid petals)."""
    a = math.radians(degrees)
    dx, dy = math.cos(a), math.sin(a)
    nx, ny = -dy, dx

    def at(along: float, across: float) -> str:
        return pt(cx + dx * length * along + nx * across, cy + dy * length * along + ny * across)

    return (
        f"M {pt(cx, cy)} C {at(0.25, width * 0.9)} {at(1.05, width * 1.1)} {at(1.0, 0)} "
        f"C {at(1.05, -width * 1.1)} {at(0.25, -width * 0.9)} {pt(cx, cy)} Z"
    )


def leaf(d: Drawing, x: float, y: float, degrees: float, length: float, width: float) -> None:
    d.path(petal(x, y, degrees, length, width, tip=0.45), width=2.6, fill=True)
    ex, ey = polar(x, y, length * 0.82, degrees)
    d.line(x, y, ex, ey, width=1.6)


def spiral(cx: float, cy: float, r0: float, r1: float, turns: float, start: float = 0) -> str:
    steps = int(36 * turns)
    points = []
    for i in range(steps + 1):
        t = i / steps
        r = r0 + (r1 - r0) * t
        points.append(pt(*polar(cx, cy, r, start + 360 * turns * t)))
    return "M " + " L ".join(points)


def curve(*points: tuple[float, float]) -> str:
    """A smooth stem through points (Catmull-Rom as cubic Beziers)."""
    out = f"M {pt(*points[0])}"
    for i in range(len(points) - 1):
        p0 = points[max(0, i - 1)]
        p1, p2 = points[i], points[i + 1]
        p3 = points[min(len(points) - 1, i + 2)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        out += f" C {pt(*c1)} {pt(*c2)} {pt(*p2)}"
    return out


def scallop(cx: float, cy: float, r: float, lobes: int, depth: float, start: float = 0) -> str:
    """A closed wavy ring: ruffled peony and carnation edges."""
    out = ""
    for i in range(lobes):
        a0 = start + 360 * i / lobes
        a1 = start + 360 * (i + 1) / lobes
        p0, p1 = polar(cx, cy, r, a0), polar(cx, cy, r, a1)
        mid = polar(cx, cy, r + depth, (a0 + a1) / 2)
        out += (f"M {pt(*p0)} " if i == 0 else "") + f"Q {pt(*mid)} {pt(*p1)} "
    return out + "Z"


def rose_head(d: Drawing, cx: float, cy: float, r: float) -> None:
    d.path(spiral(cx, cy, r * 0.12, r * 0.62, 2.2, start=-90), width=2.4)
    for k in range(5):
        a = -90 + k * 72
        p0, p1 = polar(cx, cy, r * 0.62, a - 46), polar(cx, cy, r * 0.62, a + 46)
        c0, c1 = polar(cx, cy, r * 1.18, a - 30), polar(cx, cy, r * 1.18, a + 30)
        d.path(f"M {pt(*p0)} C {pt(*c0)} {pt(*c1)} {pt(*p1)}", width=2.8)


def stem(d: Drawing, *points: tuple[float, float]) -> None:
    d.path(curve(*points), width=3.2)


# --- the fifteen ---------------------------------------------------------------


def atirgul() -> Drawing:
    d = Drawing()
    rose_head(d, 100, 78, 42)
    stem(d, (100, 118), (96, 150), (104, 192))
    leaf(d, 98, 146, 200, 38, 13)
    leaf(d, 101, 166, -20, 34, 11)
    return d


def kust_atirgul() -> Drawing:
    d = Drawing()
    stem(d, (100, 194), (98, 150), (92, 118), (70, 88))
    stem(d, (98, 150), (112, 118), (134, 92))
    stem(d, (95, 128), (100, 98), (102, 70))
    rose_head(d, 66, 78, 20)
    rose_head(d, 138, 82, 22)
    rose_head(d, 102, 52, 19)
    for x, y, a in ((80, 112, 210), (122, 114, 330)):
        d.path(petal(x, y, a, 18, 7), width=2.4)
    leaf(d, 97, 168, 205, 30, 10)
    leaf(d, 99, 140, -25, 26, 9)
    return d


def lola() -> Drawing:
    d = Drawing()
    d.path(
        "M 70 62 C 66 88 76 112 100 116 C 124 112 134 88 130 62 C 120 74 112 80 100 70 "
        "C 88 80 80 74 70 62 Z",
        width=3,
        fill=True,
    )
    d.path("M 100 70 C 92 56 94 40 100 30 C 106 40 108 56 100 70", width=2.6)
    d.path("M 70 62 C 80 66 88 76 92 94", width=2)
    d.path("M 130 62 C 120 66 112 76 108 94", width=2)
    stem(d, (100, 116), (101, 150), (99, 194))
    d.path("M 99 186 C 72 170 62 140 70 108 C 82 132 92 156 99 172", width=2.6, fill=True)
    d.path("M 101 178 C 126 160 136 136 130 112 C 118 132 108 150 101 164", width=2.6, fill=True)
    return d


def xrizantema() -> Drawing:
    d = Drawing()
    cx, cy = 100, 82
    for k in range(24):
        d.path(petal(*polar(cx, cy, 10, k * 15), k * 15, 44, 5.5, tip=0.7), width=2)
    for k in range(16):
        d.path(petal(*polar(cx, cy, 8, k * 22.5 + 11), k * 22.5 + 11, 26, 5, tip=0.7), width=1.8)
    d.circle(cx, cy, 9, width=2.4)
    stem(d, (100, 128), (103, 160), (98, 194))
    # A lobed chrysanthemum leaf: three rounded lobes along a midrib.
    d.path(
        "M 102 166 C 108 154 118 150 124 156 C 128 146 140 146 142 154 "
        "C 150 150 158 156 152 164 C 146 172 132 172 124 170 C 116 172 108 172 102 166 Z",
        width=2.4,
        fill=True,
    )
    d.path("M 102 166 C 120 162 136 160 150 158", width=1.4)
    leaf(d, 101, 146, 205, 30, 10)
    return d


def gerbera() -> Drawing:
    d = Drawing()
    cx, cy = 100, 80
    for k in range(20):
        d.path(round_petal(*polar(cx, cy, 16, k * 18), k * 18, 40, 6.5), width=2.2)
    d.circle(cx, cy, 16, width=2.6)
    d.circle(cx, cy, 9, width=2.2, fill=True)
    for k in range(12):
        x, y = polar(cx, cy, 12.5, k * 30)
        d.circle(x, y, 1.2, width=1.2, fill=True)
    stem(d, (100, 122), (99, 160), (101, 194))
    leaf(d, 100, 176, 215, 34, 11)
    return d


def liliya() -> Drawing:
    d = Drawing()
    cx, cy = 96, 84
    for k in range(6):
        a = -90 + k * 60
        d.path(petal(cx, cy, a, 60, 15, tip=0.5), width=2.6, fill=k % 2 == 0)
        mx, my = polar(cx, cy, 38, a)
        d.line(cx, cy, mx, my, width=1.4)
    for a in (-60, -30, 0, 30, 60, 90):
        ex, ey = polar(cx, cy, 30, a - 40)
        d.path(f"M {pt(cx, cy)} Q {pt(*polar(cx, cy, 18, a - 30))} {pt(ex, ey)}", width=1.6)
        d.ellipse(ex, ey, 3.4, 2, width=1.6)
    stem(d, (110, 116), (120, 150), (126, 194))
    leaf(d, 120, 150, 170, 40, 10)
    return d


def pion() -> Drawing:
    d = Drawing()
    cx, cy = 100, 82
    d.path(scallop(cx, cy, 44, 9, 9), width=2.8, fill=True)
    d.path(scallop(cx, cy, 31, 7, 8, start=20), width=2.6)
    d.path(scallop(cx, cy, 18, 6, 6, start=10), width=2.4)
    d.path(spiral(cx, cy, 2, 9, 1.4), width=2)
    stem(d, (100, 134), (98, 164), (101, 194))
    leaf(d, 99, 150, 200, 40, 14)
    leaf(d, 100, 158, -15, 38, 13)
    return d


def gortenziya() -> Drawing:
    d = Drawing()
    centres: list[tuple[float, float]] = []
    for row in range(-3, 4):
        for col in range(-3, 4):
            x = 100 + col * 17 + (row % 2) * 8.5
            y = 80 + row * 14.5
            if (x - 100) ** 2 / 54**2 + (y - 80) ** 2 / 46**2 <= 1:
                centres.append((x, y))
    for x, y in centres:
        for k in range(4):
            d.path(round_petal(x, y, 45 + k * 90, 8, 4), width=1.6)
        d.circle(x, y, 1.3, width=1.2, fill=True)
    stem(d, (100, 126), (100, 160), (100, 194))
    leaf(d, 98, 140, 160, 48, 17)
    leaf(d, 102, 146, 20, 46, 16)
    return d


def eustoma() -> Drawing:
    d = Drawing()
    d.path(
        "M 62 70 C 58 100 76 118 96 120 C 118 120 134 102 132 72 "
        "C 122 80 114 74 108 62 C 100 74 90 76 80 64 C 76 72 70 74 62 70 Z",
        width=3,
        fill=True,
    )
    d.path("M 80 64 C 86 50 102 44 108 62", width=2.4)
    d.path("M 92 56 C 98 70 110 76 120 68", width=2)
    d.path(petal(150, 72, -80, 34, 9), width=2.4)
    d.path("M 150 72 C 154 64 154 52 150 42", width=1.6)
    stem(d, (97, 120), (100, 156), (98, 194))
    stem(d, (100, 150), (130, 120), (150, 74))
    leaf(d, 99, 170, 200, 28, 12)
    leaf(d, 118, 130, 130, 24, 9)
    return d


def chinnigul() -> Drawing:
    d = Drawing()
    # The head: a closed fan from the calyx, its top edge frilled.
    teeth = 14
    out = "M 92 104 L 56 72"
    for k in range(teeth):
        a0 = 200 + 140 * k / teeth
        a1 = 200 + 140 * (k + 1) / teeth
        tip = polar(100, 104, 58 + (k % 3) * 3, (a0 + a1) / 2)
        out += f" L {pt(*tip)} L {pt(*polar(100, 104, 48, a1))}"
    out += " L 108 104 Z"
    d.path(out, width=2.6, fill=True)
    # Inner frills: two shorter rows of the same edge.
    for radius, count in ((38, 10), (26, 7)):
        row = ""
        for k in range(count):
            a0 = 215 + 110 * k / count
            a1 = 215 + 110 * (k + 1) / count
            start = polar(100, 104, radius - 6, a0)
            row += f"M {pt(*start)} " if k == 0 else ""
            tip = polar(100, 104, radius, (a0 + a1) / 2)
            row += f"L {pt(*tip)} L {pt(*polar(100, 104, radius - 6, a1))} "
        d.path(row.strip(), width=1.8)
    d.path("M 92 104 L 94 126 L 106 126 L 108 104", width=2.4, fill=True)
    d.line(97, 108, 97, 124, width=1.3)
    d.line(103, 108, 103, 124, width=1.3)
    stem(d, (100, 126), (99, 160), (101, 194))
    d.path("M 99 150 C 84 140 76 128 74 112", width=2.2)
    d.path("M 101 168 C 116 160 124 148 128 134", width=2.2)
    return d


def orxideya() -> Drawing:
    d = Drawing()
    cx, cy = 92, 74
    d.path(petal(cx, cy, -90, 40, 10), width=2.4)
    d.path(petal(cx, cy, 145, 40, 10), width=2.4)
    d.path(petal(cx, cy, 35, 40, 10), width=2.4)
    d.path(round_petal(cx, cy, -150, 42, 17), width=2.8, fill=True)
    d.path(round_petal(cx, cy, -30, 42, 17), width=2.8, fill=True)
    d.path(
        f"M {pt(cx - 9, cy + 6)} C {pt(cx - 14, cy + 30)} {pt(cx + 14, cy + 30)} "
        f"{pt(cx + 9, cy + 6)} C {pt(cx + 4, cy + 14)} {pt(cx - 4, cy + 14)} "
        f"{pt(cx - 9, cy + 6)} Z",
        width=2.4,
    )
    d.path(f"M {pt(cx - 6, cy + 26)} Q {pt(cx - 14, cy + 34)} {pt(cx - 8, cy + 38)}", width=1.6)
    d.path(f"M {pt(cx + 6, cy + 26)} Q {pt(cx + 14, cy + 34)} {pt(cx + 8, cy + 38)}", width=1.6)
    stem(d, (150, 194), (150, 140), (138, 104), (120, 86))
    for x, y in ((146, 126), (151, 150)):
        d.ellipse(x + 8, y, 6, 8, width=2)
    leaf(d, 150, 186, 200, 44, 15)
    return d


def alstromeriya() -> Drawing:
    d = Drawing()
    for cx, cy, tilt in ((70, 72, -14), (128, 66, 12), (100, 44, 0)):
        for k in range(6):
            a = -90 + tilt + (k - 2.5) * 22
            d.path(round_petal(cx, cy + 22, a, 34, 7.5), width=2.2)
        for k in range(3):
            a = -90 + tilt + (k - 1) * 20
            x0, y0 = polar(cx, cy + 22, 14, a)
            x1, y1 = polar(cx, cy + 22, 22, a)
            d.line(x0, y0, x1, y1, width=1.4)
    stem(d, (100, 194), (100, 140), (72, 98))
    stem(d, (100, 140), (128, 92))
    stem(d, (100, 140), (100, 70))
    leaf(d, 100, 162, 210, 34, 9)
    leaf(d, 100, 170, -30, 32, 9)
    return d


def mimoza() -> Drawing:
    d = Drawing()
    stem(d, (40, 186), (80, 140), (120, 96), (164, 52))
    for t in range(9):
        x, y = 50 + t * 13, 176 - t * 14
        for side in (-1, 1):
            a = -45 + side * 70
            ex, ey = polar(x, y, 22, a)
            d.line(x, y, ex, ey, width=1.6)
            for s in range(1, 5):
                px, py = polar(x, y, 4.5 * s, a)
                for sign in (-1, 1):
                    lx, ly = polar(px, py, 4, a + sign * 60)
                    d.line(px, py, lx, ly, width=1.1)
    for x, y, r in (
        (122, 70, 9),
        (142, 82, 8),
        (104, 58, 8),
        (150, 58, 7),
        (130, 46, 7),
        (112, 82, 6),
        (160, 40, 6),
    ):
        d.circle(x, y, r, width=1.8, fill=False)
        for k in range(10):
            x0, y0 = polar(x, y, r, k * 36)
            x1, y1 = polar(x, y, r + 3.5, k * 36)
            d.line(x0, y0, x1, y1, width=1.1)
    return d


def aralash() -> Drawing:
    d = Drawing()
    rose_head(d, 76, 70, 24)
    for k in range(12):
        d.path(round_petal(*polar(128, 64, 7, k * 30), k * 30, 18, 4), width=1.8)
    d.circle(128, 64, 7, width=2, fill=True)
    d.path(
        "M 92 30 C 90 44 96 54 104 56 C 112 54 118 44 116 30 C 110 36 106 38 104 32 "
        "C 102 38 98 36 92 30 Z",
        width=2.4,
        fill=True,
    )
    for x, y, a in ((60, 98, 220), (146, 92, -40), (104, 60, -95)):
        leaf(d, x, y, a, 26, 8)
    d.path("M 56 96 L 144 96 L 108 186 L 92 186 Z", width=3, fill=True)
    d.path("M 70 96 L 98 186 M 130 96 L 102 186", width=1.6)
    d.path(
        "M 88 138 C 76 126 70 140 84 146 C 92 148 98 142 100 140 "
        "C 102 142 108 148 116 146 C 130 140 124 126 112 138",
        width=2.4,
    )
    d.path("M 100 140 C 96 154 90 162 84 166 M 100 140 C 104 154 110 162 116 166", width=2)
    return d


def quti() -> Drawing:
    d = Drawing()
    d.ellipse(100, 112, 62, 16, width=3)
    d.path("M 38 112 L 38 170 C 38 196 162 196 162 170 L 162 112", width=3)
    d.path("M 38 140 C 38 160 162 160 162 140", width=2)
    d.line(100, 127, 100, 186, width=2.4)
    d.path(
        "M 100 140 C 86 126 76 134 86 144 C 92 148 98 144 100 140 "
        "C 102 144 108 148 114 144 C 124 134 114 126 100 140 Z",
        width=2.4,
    )
    for x, y, r in ((72, 98, 16), (100, 90, 18), (128, 98, 16), (86, 76, 13), (116, 76, 13)):
        rose_head(d, x, y, r)
    leaf(d, 54, 106, 200, 20, 7)
    leaf(d, 146, 106, -20, 20, 7)
    return d


def sprig() -> Drawing:
    """A leaf sprig every layout may use as a secondary ornament."""
    d = Drawing()
    stem(d, (30, 170), (80, 120), (120, 80), (170, 30))
    for k in range(5):
        t = 0.15 + k * 0.17
        x, y = 30 + 140 * t, 170 - 140 * t
        leaf(d, x, y, -45 - 55, 30 - k * 2, 9)
        leaf(d, x, y, -45 + 55, 30 - k * 2, 9)
    return d


def sparkle() -> Drawing:
    d = Drawing()
    d.path(
        "M 100 20 C 106 80 120 94 180 100 C 120 106 106 120 100 180 "
        "C 94 120 80 106 20 100 C 80 94 94 80 100 20 Z",
        width=3,
        fill=True,
    )
    return d


MOTIFS = {
    "atirgul": atirgul,
    "kust_atirgul": kust_atirgul,
    "lola": lola,
    "xrizantema": xrizantema,
    "gerbera": gerbera,
    "liliya": liliya,
    "pion": pion,
    "gortenziya": gortenziya,
    "eustoma": eustoma,
    "chinnigul": chinnigul,
    "orxideya": orxideya,
    "alstromeriya": alstromeriya,
    "mimoza": mimoza,
    "aralash": aralash,
    "quti": quti,
    "sprig": sprig,
    "sparkle": sparkle,
}


def render_all() -> dict[str, str]:
    return {name: build().svg(name) for name, build in MOTIFS.items()}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, svg in render_all().items():
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote {len(MOTIFS)} motifs to {OUT}")


if __name__ == "__main__":
    main()
