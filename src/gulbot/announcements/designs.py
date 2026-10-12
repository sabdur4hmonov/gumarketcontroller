"""The CP23 overlays: 10 layouts x 15 flower themes on the owner's photo.

Every text is FITTED into a container the layout declares -- the font shrinks
to a floor, and only then may a name be shortened with an ellipsis; a price is
never shortened (its floor is low enough for a 9-digit price in the narrowest
container). Each drawn text's real bounding box is RECORDED with its container,
so the overflow tests check geometry, not pixels.

Text is only ever drawn on a solid panel in a colour pair whose contrast is
tested (`text_on`), never straight onto the photo. Motifs are cached rasters
(motifs.py); fonts are cached per size.
"""

from __future__ import annotations

import io
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

from .flower_templates import money, split_template
from .layouts import Layout
from .motifs import raster
from .themes import FlowerTheme, Palette

FONTS = Path(__file__).with_name("assets") / "fonts"
BOLD = FONTS / "NotoSans-SemiBold.ttf"
REGULAR = FONTS / "NotoSans-Regular.ttf"
ELLIPSIS = "…"
MAX_PHOTO_BYTES = 10_000_000
MAX_PHOTO_PIXELS = 25_000_000
#: The template picker's previews: ten at once, so smaller than a post.
PREVIEW_LONGEST = 720

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class TextBox:
    role: str
    text: str
    drawn: Box
    container: Box
    size: int
    truncated: bool


@dataclass
class Rendered:
    jpeg: bytes
    width: int
    height: int
    boxes: list[TextBox] = field(default_factory=list)
    seconds: float = 0.0


@dataclass(frozen=True)
class Texts:
    """What a design writes: already localised by the caller."""

    name: str
    price: str
    shop: str
    badge: str = ""


# --- colour -------------------------------------------------------------------


def _luminance(colour: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = ImageColor.getrgb(colour)[:3]
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_on(palette: Palette, surface: str) -> str:
    """The palette's text colour with the better contrast on `surface`."""
    return max((palette.ink, palette.bg), key=lambda colour: contrast(colour, surface))


# --- drawing ------------------------------------------------------------------


@lru_cache(maxsize=256)
def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD if bold else REGULAR), size)


class Canvas:
    def __init__(self, image: Image.Image) -> None:
        self.image = image
        self.draw = ImageDraw.Draw(image)
        self.boxes: list[TextBox] = []

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size

    def panel(self, box: Box, colour: str, radius: int = 0) -> None:
        if radius:
            self.draw.rounded_rectangle(box, radius=radius, fill=colour)
        else:
            self.draw.rectangle(box, fill=colour)

    def motif(self, name: str, centre: tuple[int, int], size: int, colour: str) -> None:
        if size < 8:
            return
        art = raster(name, size, colour)
        self.image.paste(art, (centre[0] - size // 2, centre[1] - size // 2), art)

    def text(
        self,
        role: str,
        text: str,
        container: Box,
        colour: str,
        *,
        bold: bool = True,
        align: str = "left",
        floor: int = 12,
        truncate: bool = True,
    ) -> TextBox:
        x0, y0, x1, y1 = container
        width, height = x1 - x0, y1 - y0
        size = max(floor, int(height * 0.92))
        text = " ".join(text.split())
        truncated = False

        def measure(value: str, points: int) -> tuple[int, int, int, int]:
            box = self.draw.textbbox((0, 0), value, font=font(bold, points))
            return int(box[0]), int(box[1]), int(box[2]), int(box[3])

        while True:
            left, top, right, bottom = measure(text, size)
            if (right - left <= width and bottom - top <= height) or size <= floor:
                break
            size -= 1
        left, top, right, bottom = measure(text, size)
        if right - left > width and truncate:
            while (
                text
                and measure(text + ELLIPSIS, size)[2] - measure(text + ELLIPSIS, size)[0] > width
            ):
                text = text[:-1].rstrip()
            text = text + ELLIPSIS if text else ""
            truncated = True
            left, top, right, bottom = measure(text, size)
        ink_w, ink_h = right - left, bottom - top
        if align == "center":
            x = x0 + (width - ink_w) // 2
        elif align == "right":
            x = x1 - ink_w
        else:
            x = x0
        y = y0 + (height - ink_h) // 2
        self.draw.text((x - left, y - top), text, font=font(bold, size), fill=colour)
        drawn = (x, y, x + ink_w, y + ink_h)
        box = TextBox(role, text, drawn, container, size, truncated)
        self.boxes.append(box)
        return box

    def stack(
        self,
        container: Box,
        rows: Sequence[tuple[str, str, float, bool]],
        colour: str,
        *,
        align: str = "left",
        gap: float = 0.08,
    ) -> None:
        """Rows of (role, text, share of the height, bold), top to bottom."""
        x0, y0, x1, y1 = container
        shares = [row[2] for row in rows if row[1]]
        total = sum(shares) or 1
        space = int((y1 - y0) * gap)
        usable = (y1 - y0) - space * max(0, len(shares) - 1)
        y = y0
        for role, text, share, bold in rows:
            if not text:
                continue
            h = int(usable * share / total)
            self.text(
                role,
                text,
                (x0, y, x1, y + h),
                colour,
                bold=bold,
                align=align,
                truncate=role != "price",
                floor=10 if role == "price" else 12,
            )
            y += h + space


# --- photos -------------------------------------------------------------------


def open_photo(photo: bytes) -> Image.Image:
    """Decode an owner's photo safely: size limits, EXIF rotation, RGB."""
    if len(photo) > MAX_PHOTO_BYTES:
        raise ValueError("photo too large")
    with Image.open(io.BytesIO(photo)) as source:
        if source.width * source.height > MAX_PHOTO_PIXELS:
            raise ValueError("photo dimensions too large")
        return ImageOps.exif_transpose(source).convert("RGB")


def post_canvas(photo: bytes, *, longest: int = 1280) -> Image.Image:
    image = open_photo(photo)
    image.thumbnail((longest, longest))
    if image.width < 640:  # legible even for a tiny upload, without distortion
        image = image.resize((640, max(400, int(image.height * 640 / image.width))))
    return image


def encode(image: Image.Image, quality: int = 90) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()


# --- the ten post layouts -----------------------------------------------------

PostDraw = Callable[[Canvas, FlowerTheme, Palette, Texts], None]


def _band(c: Canvas, top: int, p: Palette) -> Box:
    w, h = c.size
    c.panel((0, top, w, h), p.bg)
    return (0, top, w, h)


def _classic(c: Canvas, t: FlowerTheme, p: Palette, x: Texts) -> None:
    w, h = c.size
    band = max(int(h * 0.24), 120)
    _, top, _, _ = _band(c, h - band, p)
    pad = int(band * 0.12)
    art = band - 2 * pad
    c.motif(t.motif, (pad + art // 2, top + band // 2), art, p.accent)
    ink = text_on(p, p.bg)
    c.stack(
        (pad * 2 + art, top + pad, w - pad, h - pad),
        [
            ("name", x.name, 0.22, False),
            ("price", x.price, 0.48, True),
            ("shop", x.shop, 0.3, False),
        ],
        ink,
    )


def _minimal(c: Canvas, t: FlowerTheme, p: Palette, x: Texts) -> None:
    w, h = c.size
    pad = max(12, w // 28)
    panel_w, panel_h = int(w * 0.62), max(int(h * 0.16), 96)
    box = (pad, h - pad - panel_h, pad + panel_w, h - pad)
    c.panel(box, p.soft, radius=8)
    c.draw.line((box[0] + 10, box[1] + 8, box[0] + 10, box[3] - 8), fill=p.accent, width=4)
    ink = text_on(p, p.soft)
    c.stack(
        (box[0] + 24, box[1] + 10, box[2] - 12, box[3] - 10),
        [("price", x.price, 0.6, True), ("shop", x.shop, 0.4, False)],
        ink,
    )
    corner = max(64, w // 9)
    c.panel((w - pad - corner, pad, w - pad, pad + corner), p.soft, radius=corner // 2)
    c.motif(t.motif, (w - pad - corner // 2, pad + corner // 2), int(corner * 0.8), p.accent)


def _festive(c: Canvas, t: FlowerTheme, p: Palette, x: Texts) -> None:
    w, h = c.size
    pad = max(12, w // 30)
    step = max(28, w // 14)
    for i, cx in enumerate(range(pad, w - pad + 1, step)):
        size = max(18, step // 2) if i % 3 else max(24, int(step * 0.7))
        c.motif(
            "sparkle",
            (cx, pad + (i % 2) * size // 2 + size // 2),
            size,
            p.accent if i % 2 else p.bg,
        )
    pill_h = max(int(h * 0.2), 110)
    box = (pad, h - pad - pill_h, w - pad, h - pad)
    c.panel(box, p.bg, radius=pill_h // 2)
    art = int(pill_h * 0.86)
    c.motif(t.motif, (box[0] + pill_h // 2 + 4, box[1] + pill_h // 2), art, p.accent)
    c.stack(
        (box[0] + pill_h + 8, box[1] + pill_h // 8, box[2] - pill_h // 3, box[3] - pill_h // 8),
        [("price", x.price, 0.58, True), ("shop", x.shop, 0.42, False)],
        text_on(p, p.bg),
    )


def _premium(c: Canvas, t: FlowerTheme, p: Palette, x: Texts) -> None:
    w, h = c.size
    pad = max(14, w // 26)
    for inset, width in ((pad, 3), (pad + 9, 1)):
        c.draw.rectangle(
            (inset, inset, w - 1 - inset, h - 1 - inset), outline=p.accent, width=width
        )
    plate_w, plate_h = int(w * 0.7), max(int(h * 0.27), 150)
    box = ((w - plate_w) // 2, h - pad * 2 - plate_h, (w + plate_w) // 2, h - pad * 2)
    c.panel(box, p.bg, radius=6)
    c.draw.rectangle((box[0] + 6, box[1] + 6, box[2] - 6, box[3] - 6), outline=p.accent, width=1)
    art = int(plate_h * 0.3)
    c.motif(t.motif, ((box[0] + box[2]) // 2, box[1] + art // 2 + 10), art, p.accent)
    c.stack(
        (box[0] + 18, box[1] + art + 16, box[2] - 18, box[3] - 12),
        [
            ("name", x.name, 0.26, False),
            ("price", x.price, 0.44, True),
            ("shop", x.shop, 0.3, False),
        ],
        text_on(p, p.bg),
        align="center",
    )


def _playful(c: Canvas, t: FlowerTheme, p: Palette, x: Texts) -> None:
    w, h = c.size
    pad = max(12, w // 26)
    bubble_w, bubble_h = int(w * 0.66), max(int(h * 0.22), 120)
    box = (pad, h - pad - bubble_h, pad + bubble_w, h - pad)
    c.panel(box, p.bg, radius=bubble_h // 3)
    c.draw.polygon(
        (
            (box[0] + bubble_w // 5, box[1] + 2),
            (box[0] + bubble_w // 3, box[1] + 2),
            (box[0] + bubble_w // 6, box[1] - bubble_h // 4),
        ),
        fill=p.bg,
    )
    c.stack(
        (
            box[0] + bubble_h // 4,
            box[1] + bubble_h // 9,
            box[2] - bubble_h // 4,
            box[3] - bubble_h // 9,
        ),
        [
            ("name", x.name, 0.28, True),
            ("price", x.price, 0.42, True),
            ("shop", x.shop, 0.3, False),
        ],
        text_on(p, p.bg),
    )
    dot = max(70, w // 7)
    for cx, cy, scale in (
        (w - pad - dot // 2, pad + dot // 2, 1.0),
        (w - pad - dot // 2, h - pad - int(dot * 0.7), 0.8),
        (pad + dot // 2, pad + dot // 2, 0.7),
    ):
        size = int(dot * scale)
        c.panel(
            (cx - size // 2, cy - size // 2, cx + size // 2, cy + size // 2),
            p.soft,
            radius=size // 2,
        )
        c.motif(t.motif, (cx, cy), int(size * 0.8), p.accent)


def _sale(c: Canvas, t: FlowerTheme, p: Palette, x: Texts) -> None:
    w, h = c.size
    pad = max(12, w // 28)
    disc = max(int(min(w, h) * 0.42), 200)
    cx, cy = w - pad - disc // 2, pad + disc // 2
    c.panel(
        (cx - disc // 2, cy - disc // 2, cx + disc // 2, cy + disc // 2), p.bg, radius=disc // 2
    )
    c.draw.ellipse(
        (cx - disc // 2 + 8, cy - disc // 2 + 8, cx + disc // 2 - 8, cy + disc // 2 - 8),
        outline=p.accent,
        width=3,
    )
    inner = int(disc * 0.76)
    c.stack(
        (cx - inner // 2, cy - inner // 3, cx + inner // 2, cy + inner // 3),
        [("badge", x.badge, 0.45, True), ("price", x.price, 0.55, True)],
        text_on(p, p.bg),
        align="center",
    )
    strip = max(int(h * 0.11), 60)
    c.panel((0, h - strip, w, h), p.ink)
    c.motif(t.motif, (pad + strip // 2, h - strip // 2), int(strip * 0.85), p.bg)
    c.text(
        "shop",
        x.shop,
        (pad + strip + 6, h - strip + strip // 6, w - pad, h - strip // 6),
        text_on(p, p.ink),
        bold=False,
    )


def _gift(c: Canvas, t: FlowerTheme, p: Palette, x: Texts) -> None:
    w, h = c.size
    pad = max(12, w // 28)
    ribbon = max(16, w // 22)
    rx = int(w * 0.18)
    c.panel((rx - ribbon // 2, 0, rx + ribbon // 2, h), p.accent)
    kx, ky = rx, int(h * 0.2)
    loop = ribbon * 2
    for left in (kx - 2 * loop, kx):
        c.draw.ellipse(
            (left, ky - loop // 2, left + 2 * loop, ky + loop // 2),
            outline=p.accent,
            width=max(6, ribbon // 2),
        )
    c.panel((kx - ribbon // 2, ky - ribbon // 2, kx + ribbon // 2, ky + ribbon // 2), p.ink)
    tag_w, tag_h = int(w * 0.56), max(int(h * 0.26), 140)
    box = (w - pad - tag_w, h - pad - tag_h, w - pad, h - pad)
    c.panel(box, p.bg, radius=14)
    hole = max(8, tag_h // 12)
    c.draw.ellipse(
        (box[0] + 14, box[1] + 14, box[0] + 14 + hole, box[1] + 14 + hole), fill=p.accent
    )
    art = int(tag_h * 0.42)
    c.motif(t.motif, (box[2] - art // 2 - 10, box[1] + art // 2 + 8), art, p.accent)
    c.stack(
        (box[0] + 18, box[1] + 14 + hole + 4, box[2] - art - 18, box[3] - 12),
        [
            ("badge", x.badge, 0.26, True),
            ("price", x.price, 0.42, True),
            ("shop", x.shop, 0.32, False),
        ],
        text_on(p, p.bg),
    )


def _new_arrival(c: Canvas, t: FlowerTheme, p: Palette, x: Texts) -> None:
    w, h = c.size
    pad = max(12, w // 28)
    label_h = max(int(h * 0.09), 52)
    label = (pad, pad, pad + int(w * 0.42), pad + label_h)
    c.panel(label, p.ink, radius=label_h // 2)
    c.text(
        "badge",
        x.badge,
        (
            label[0] + label_h // 2,
            label[1] + label_h // 6,
            label[2] - label_h // 2,
            label[3] - label_h // 6,
        ),
        text_on(p, p.ink),
        align="center",
    )
    band = max(int(h * 0.22), 120)
    _band(c, h - band, p)
    c.draw.line((0, h - band, w, h - band), fill=p.accent, width=4)
    art = int(band * 0.8)
    c.motif(t.motif, (w - pad - art // 2, h - band // 2), art, p.accent)
    c.stack(
        (pad, h - band + band // 9, w - art - 2 * pad, h - band // 9),
        [
            ("name", x.name, 0.3, True),
            ("price", x.price, 0.42, True),
            ("shop", x.shop, 0.28, False),
        ],
        text_on(p, p.bg),
    )


def _price_first(c: Canvas, t: FlowerTheme, p: Palette, x: Texts) -> None:
    w, h = c.size
    pad = max(12, w // 28)
    band = max(int(h * 0.32), 170)
    _band(c, h - band, p)
    art = int(band * 0.62)
    c.motif(t.motif, (w - pad - art // 2, h - band + art // 2 + pad), art, p.accent)
    c.stack(
        (pad, h - band + pad, w - 2 * pad - art, h - pad),
        [("price", x.price, 0.62, True), ("shop", x.shop, 0.38, False)],
        text_on(p, p.bg),
        gap=0.05,
    )


def _story_card(c: Canvas, t: FlowerTheme, p: Palette, x: Texts) -> None:
    w, h = c.size
    pad = max(14, w // 20)
    card_h = max(int(h * 0.3), 160)
    box = (pad, h - pad - card_h, w - pad, h - pad)
    c.panel(box, p.soft, radius=22)
    art = int(card_h * 0.42)
    c.panel(
        ((w - art) // 2 - 6, box[1] - art // 2 - 6, (w + art) // 2 + 6, box[1] + art // 2 + 6),
        p.bg,
        radius=art // 2 + 6,
    )
    c.motif(t.motif, (w // 2, box[1]), art, p.accent)
    c.stack(
        (box[0] + 20, box[1] + art // 2 + 10, box[2] - 20, box[3] - 14),
        [
            ("name", x.name, 0.28, False),
            ("price", x.price, 0.42, True),
            ("shop", x.shop, 0.3, False),
        ],
        text_on(p, p.soft),
        align="center",
    )


POST_LAYOUTS: dict[str, PostDraw] = {
    "classic": _classic,
    "minimal": _minimal,
    "festive": _festive,
    "premium": _premium,
    "playful": _playful,
    "sale": _sale,
    "gift": _gift,
    "new_arrival": _new_arrival,
    "price_first": _price_first,
    "story_card": _story_card,
}


def texts_for(
    theme: FlowerTheme, layout: Layout, *, price: int, shop_name: str, lang: str
) -> Texts:
    return Texts(
        name=theme.name(lang),
        price=money(price, lang),
        shop=" ".join(shop_name.split())[:120],
        badge=layout.text(layout.badge, lang),
    )


def render_post(
    photo: bytes,
    *,
    template: str,
    price: int,
    colour: str,
    shop_name: str,
    lang: str = "uz",
    longest: int = 1280,
) -> Rendered:
    """The first photo of an announcement with its template's overlay."""
    started = time.perf_counter()
    theme, layout = split_template(template)
    palette = theme.palette_for(colour)
    canvas = Canvas(post_canvas(photo, longest=longest))
    POST_LAYOUTS[layout.id](
        canvas,
        theme,
        palette,
        texts_for(theme, layout, price=price, shop_name=shop_name, lang=lang),
    )
    jpeg = encode(canvas.image)
    w, h = canvas.size
    return Rendered(jpeg, w, h, canvas.boxes, time.perf_counter() - started)
