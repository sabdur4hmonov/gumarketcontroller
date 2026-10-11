"""Ten original Pillow designs. No downloaded artwork; OFL Noto Sans fonts."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

IMAGE_STYLES = (
    "price-pill",
    "ivory-frame",
    "gold-corners",
    "rose-ribbon",
    "emerald-card",
    "midnight",
    "pastel-label",
    "festive-dots",
    "minimal-line",
    "geometric-badge",
)
IMAGE_LABELS = {
    "none": "Ustamasiz",
    "price-pill": "Narx belgisi",
    "ivory-frame": "Och ramka",
    "gold-corners": "Oltin burchaklar",
    "rose-ribbon": "Pushti lenta",
    "emerald-card": "Zumrad",
    "midnight": "Tungi",
    "pastel-label": "Pastel yorliq",
    "festive-dots": "Bayram nuqtalari",
    "minimal-line": "Minimal chiziq",
    "geometric-badge": "Geometrik nishon",
}
FONT = Path(__file__).with_name("assets") / "fonts" / "NotoSans-SemiBold.ttf"
PALETTES = (
    ("#fff7ef", "#762f38"),
    ("#ffffee", "#494333"),
    ("#d3af66", "#241c13"),
    ("#aa385c", "#ffffff"),
    ("#175d4c", "#ffffff"),
    ("#172438", "#ffffff"),
    ("#e9d8ef", "#44304f"),
    ("#ffc65e", "#432e21"),
    ("#ffffff", "#242424"),
    ("#e4ede9", "#194538"),
)


def overlay(photo: bytes, *, style: str, price: int, shop_name: str) -> bytes:
    if style == "none":
        return photo
    if style not in IMAGE_STYLES:
        raise ValueError("unknown image style")
    if len(photo) > 10_000_000:
        raise ValueError("photo too large")
    with Image.open(io.BytesIO(photo)) as source:
        if source.width * source.height > 25_000_000:
            raise ValueError("photo dimensions too large")
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1280, 1280))
    # Keep a legible canvas even for a tiny upload, without distortion.
    if image.width < 640:
        image = image.resize((640, max(400, int(image.height * 640 / image.width))))
    w, h = image.size
    d = ImageDraw.Draw(image)
    bg, ink = PALETTES[IMAGE_STYLES.index(style)]
    margin = max(12, w // 35)
    band = max(115, h // 5)
    if style == "ivory-frame":
        d.rectangle((0, 0, w - 1, h - 1), outline=bg, width=margin)
    elif style == "gold-corners":
        for x, y, dx, dy in (
            (margin, margin, 1, 1),
            (w - margin, margin, -1, 1),
            (margin, h - margin, 1, -1),
            (w - margin, h - margin, -1, -1),
        ):
            d.line((x + dx * w // 6, y, x, y, x, y + dy * h // 6), fill=bg, width=5)
    elif style == "minimal-line":
        d.line((margin, h - band - margin, w - margin, h - band - margin), fill=bg, width=4)
    elif style == "festive-dots":
        for i in range(14):
            x, y = margin + i * (w - 2 * margin) // 14, margin + (i % 3) * 14
            d.ellipse((x, y, x + 10, y + 10), fill=bg)
    elif style == "geometric-badge":
        d.polygon(
            ((w - margin, margin), (w - margin - 90, margin), (w - margin, margin + 90)), fill=bg
        )
    radius = 35 if style in {"price-pill", "pastel-label"} else 6
    left = 0 if style in {"rose-ribbon", "midnight"} else margin
    d.rounded_rectangle((left, h - band - margin, w - left, h - margin), radius=radius, fill=bg)
    font_size = max(20, min(42, w // 22))
    font = ImageFont.truetype(str(FONT), font_size)
    small = ImageFont.truetype(str(FONT), max(16, font_size - 8))
    text = f"{price:,} so'm".replace(",", " ")
    name = " ".join(shop_name.split())[:100]
    while name and d.textbbox((0, 0), name, font=small)[2] > w - 4 * margin:
        name = name[:-1]
    d.text((2 * margin, h - band), text, font=font, fill=ink)
    d.text((2 * margin, h - band + font_size + 10), name, font=small, fill=ink)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue()
