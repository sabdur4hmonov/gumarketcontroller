"""Render every original CP22 caption/image design into a local HTML gallery."""

from __future__ import annotations

import argparse
import io
from html import escape, unescape
from pathlib import Path

from PIL import Image, ImageDraw

from gulbot.announcements.extraction import Fields
from gulbot.announcements.images import IMAGE_STYLES, overlay
from gulbot.announcements.templates import CAPTION_STYLES, caption


def generate(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    # Original schematic bouquet, drawn here solely as gallery demonstration.
    image = Image.new("RGB", (900, 1100), "#f1e7da")
    draw = ImageDraw.Draw(image)
    draw.polygon(((180, 460), (740, 460), (570, 1030), (410, 1030)), fill="#d5c1a9")
    for i, (x, y) in enumerate(
        ((290, 310), (410, 250), (540, 280), (650, 370), (250, 470), (440, 430), (560, 470))
    ):
        draw.line((x, y, 490, 930), fill="#426c4f", width=10)
        for dx, dy in ((-45, 0), (0, -45), (45, 0), (0, 45)):
            draw.ellipse(
                (x + dx - 50, y + dy - 50, x + dx + 50, y + dy + 50),
                fill="#a83b59" if i % 2 else "#c9506c",
            )
        draw.ellipse((x - 33, y - 33, x + 33, y + 33), fill="#78243e")
    source = io.BytesIO()
    image.save(source, format="JPEG", quality=90)
    (directory / "bouquet.jpg").write_bytes(source.getvalue())
    fields = Fields(
        flowers=["atirgul"],
        count=51,
        price=450000,
        colour="qizil",
        description="Qizil atirgullar. Mehringizni gullar bilan yetkazing.",
    )
    captions: list[str] = []
    images: list[str] = []
    for name in CAPTION_STYLES:
        body = unescape(caption(fields, style=name, shop_name="Namuna gul do'koni"))
        captions.append(
            f'<article id="caption-{name}"><h2>{name}</h2>'
            f'<img src="bouquet.jpg" alt="Namuna"><pre>{escape(body)}</pre></article>'
        )
    for name in ["none", *IMAGE_STYLES]:
        (directory / f"{name}.jpg").write_bytes(
            overlay(source.getvalue(), style=name, price=450000, shop_name="Namuna — Ўзбекистон")
        )
        images.append(
            f'<article id="image-{name}"><h2>{name}</h2>'
            f'<img src="{name}.jpg" alt="{name}"></article>'
        )
    html = (
        '<!doctype html><html lang="uz"><meta charset="utf-8">'
        "<title>CP22 uslublar galereyasi</title><style>"
        "body{background:#ede6df;color:#252127;font:16px system-ui;margin:30px}"
        "h1{font-size:30px}section{display:grid;"
        "grid-template-columns:repeat(3,minmax(0,1fr));gap:24px}"
        "article{background:white;border-radius:16px;overflow:hidden;padding:18px;"
        "box-shadow:0 3px 12px #0001}h2{font-size:20px}img{width:100%;border-radius:8px}"
        "pre{white-space:pre-wrap;font:15px/1.55 system-ui}a{color:#733d52}"
        "@media(max-width:900px){section{grid-template-columns:repeat(2,minmax(0,1fr))}}"
        "</style><h1>CP22 — 20 matn va 10 rasm uslubi</h1>"
        "<p>Original sinov guldastasi. Narx va teglar barcha uslublarda katalogga mos.</p>"
        "<h1>Matn uslublari</h1><section>"
        + "".join(captions)
        + "</section><h1>Rasm uslublari va qoplamasiz variant</h1><section>"
        + "".join(images)
        + "</section></html>"
    )
    (directory / "index.html").write_text(html, encoding="utf-8")
    print(f"Gallery: {directory / 'index.html'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/cp22-gallery"))
    generate(parser.parse_args().output)
