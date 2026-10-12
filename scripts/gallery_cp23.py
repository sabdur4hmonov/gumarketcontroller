"""Build the CP23 gallery and the render timings.

    python scripts/gallery_cp23.py

Writes docs/cp23-gallery/: index.html and one page per flower theme, each
with its 10 post templates (overlay + the exact caption) and its 10 story
layouts, at phone width (360 px). And docs/cp23-render-timings.json: how
long the real renderers take, cold (first render, motif not cached) and
warm, at full size.

The "photos" are SCHEMATIC samples drawn here from each flower's own motif
on a soft background -- original artwork for demonstration, not real
bouquets and not stock images; the gallery says so on every page.
"""

from __future__ import annotations

import html
import io
import json
import platform
import statistics
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from gulbot.announcements import motifs
from gulbot.announcements.designs import render_post
from gulbot.announcements.extraction import Fields
from gulbot.announcements.flower_templates import caption
from gulbot.announcements.layouts import LAYOUT_IDS, LAYOUTS
from gulbot.announcements.stories import STORY_LAYOUT_IDS, STORY_LAYOUTS, render_story
from gulbot.announcements.themes import FLOWER_THEME, THEMES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "cp23-gallery"
TIMINGS = ROOT / "docs" / "cp23-render-timings.json"
SHOP = "Gulshan gullari"
PHONE = 360

SAMPLE_FLOWERS = {theme: [k for k, v in FLOWER_THEME.items() if v == theme][:1] for theme in THEMES}
SAMPLE_FLOWERS["aralash"] = ["atirgul", "tyulpan", "gerbera"]
SAMPLE_FLOWERS["quti"] = ["atirgul"]
COLOURS = {theme: THEMES[theme].palettes[0].colours[0] for theme in THEMES}


def sample_photo(theme_id: str) -> bytes:
    """A schematic 'photo': the flower's motif, many times, softly lit."""
    theme = THEMES[theme_id]
    palette = theme.palettes[0]
    image = Image.new("RGB", (900, 1200), palette.soft)
    draw = ImageDraw.Draw(image)
    for i in range(1200):  # a soft vertical light
        shade = int(30 * i / 1200)
        draw.line((0, i, 900, i), fill=(250 - shade, 244 - shade, 236 - shade))
    for x, y, size in (
        (450, 520, 620),
        (230, 420, 360),
        (680, 430, 360),
        (300, 760, 300),
        (620, 760, 300),
    ):
        art = motifs.raster(theme.motif, size, palette.accent)
        image.paste(art, (x - size // 2, y - size // 2), art)
    image = image.filter(ImageFilter.GaussianBlur(0.6))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88)
    return out.getvalue()


def sample_logo() -> Image.Image:
    """A plainly labelled SAMPLE logo -- not any shop's."""
    from PIL import ImageFont

    logo = Image.new("RGBA", (520, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logo)
    draw.rounded_rectangle((4, 4, 516, 196), radius=40, outline=(122, 20, 36, 255), width=10)
    font = ImageFont.truetype(
        str(ROOT / "src/gulbot/announcements/assets/fonts/NotoSans-SemiBold.ttf"), 70
    )
    draw.text((50, 55), "NAMUNA", font=font, fill=(122, 20, 36, 255))
    return logo


def phone(jpeg: bytes, name: str) -> str:
    with Image.open(io.BytesIO(jpeg)) as image:
        small = image.convert("RGB")
        small.thumbnail((PHONE, PHONE * 2))
        small.save(OUT / "img" / name, format="JPEG", quality=80, optimize=True)
    return f"img/{name}"


def caption_html(text: str) -> str:
    # The caption is Telegram HTML already (escaped, with <b>): shown as is.
    return text.replace("\n", "<br>")


STYLE = """
:root{--bg:#f4f1ec;--ink:#2b2622;--card:#fff;--muted:#7a716a;--line:#e3ddd4}
@media (prefers-color-scheme:dark){:root{--bg:#1c1a18;--ink:#eee7df;--card:#2a2724;
--muted:#a99f95;--line:#3a3532}}
body{margin:0;font:15px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--ink)}
main{max-width:1180px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:8px 0}h2{font-size:18px;margin:28px 0 8px}
.note{color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
overflow:hidden;max-width:360px}
.card img{display:block;width:100%;height:auto}
.card .cap{padding:10px 12px;font-size:13px;white-space:normal;word-break:break-word}
.card .tag{padding:8px 12px;font-weight:600;border-bottom:1px solid var(--line)}
.stories{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}
.stories figure{margin:0}.stories img{width:100%;border-radius:10px;display:block}
figcaption{font-size:12px;color:var(--muted);margin-top:4px}
nav a{display:inline-block;margin:0 10px 6px 0}
"""


def page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='uz'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


NOTE = (
    "<p class='note'>Sample photos are schematic drawings made from each flower's own "
    "motif (original artwork for demonstration), not real bouquets and not stock "
    "images. Overlays, captions and stories are the real renderers' output.</p>"
)


def main() -> None:
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    timings: dict[str, list[float]] = {
        "post_cold": [],
        "post_warm": [],
        "story_cold": [],
        "story_warm": [],
    }
    index = [f"<h1>CP23 — {len(THEMES)} flower themes</h1>", NOTE, "<nav>"]
    for theme_id, theme in THEMES.items():
        index.append(
            f"<a href='{theme_id}.html'>{theme.emoji[0]} {html.escape(theme.names[0])}</a>"
        )
    index.append("</nav>")
    for theme_id, theme in THEMES.items():
        photo = sample_photo(theme_id)
        fields = Fields(
            flowers=SAMPLE_FLOWERS[theme_id],
            count=25,
            price=450_000,
            colour=COLOURS[theme_id],
            description="Yetkazib berish bor. Buyurtma 24/7.",
            raw="qutida" if theme_id == "quti" else "",
        )
        cards = []
        for i, layout in enumerate(LAYOUT_IDS):
            template = f"{theme_id}.{layout}"
            lang = "uz"
            started = time.perf_counter()
            rendered = render_post(
                photo,
                template=template,
                price=450_000,
                colour=COLOURS[theme_id],
                shop_name=SHOP,
                lang=lang,
            )
            timings["post_cold" if i == 0 else "post_warm"].append(time.perf_counter() - started)
            src = phone(rendered.jpeg, f"{theme_id}-post-{layout}.jpg")
            text = caption(fields, template=template, shop_name=SHOP, lang=lang)
            cards.append(
                f"<div class='card'><div class='tag'>{i + 1}. "
                f"{html.escape(LAYOUTS[layout].label[0])}"
                f"</div><img src='{src}' alt='{template}' loading='lazy'>"
                f"<div class='cap'>{caption_html(text)}</div></div>"
            )
        stories = []
        for i, layout in enumerate(STORY_LAYOUT_IDS):
            started = time.perf_counter()
            rendered = render_story(
                photo,
                theme=theme_id,
                layout=layout,
                price=450_000,
                colour=COLOURS[theme_id],
                shop_name=SHOP,
                lang="uz",
            )
            timings["story_cold" if i == 0 else "story_warm"].append(time.perf_counter() - started)
            src = phone(rendered.jpeg, f"{theme_id}-story-{layout}.jpg")
            label = STORY_LAYOUTS[layout][0].label[0]
            stories.append(
                f"<figure><img src='{src}' alt='{theme_id} story {layout}' loading='lazy'>"
                f"<figcaption>{i + 1}. {html.escape(label)}</figcaption></figure>"
            )
        body = (
            f"<p><a href='index.html'>← barcha gullar</a></p>"
            f"<h1>{theme.emoji[0]} {html.escape(theme.names[0])}</h1>{NOTE}"
            f"<h2>10 post templates (360 px)</h2><div class='grid'>{''.join(cards)}</div>"
            f"<h2>10 Instagram stories (1080×1920, shown at 180 px)</h2>"
            f"<div class='stories'>{''.join(stories)}</div>"
        )
        (OUT / f"{theme_id}.html").write_text(page(theme.names[0], body), encoding="utf-8")
        print(f"{theme_id}: done")
    # The shop's own logo (CP23 addendum): a SAMPLE, on a post and a story.
    logo = sample_logo()
    photo = sample_photo("atirgul")
    shots = [
        phone(
            render_post(
                photo,
                template=f"atirgul.{layout}",
                price=450_000,
                colour="qizil",
                shop_name=SHOP,
                logo=logo,
            ).jpeg,
            f"logo-post-{layout}.jpg",
        )
        for layout in ("classic", "new_arrival", "premium")
    ] + [
        phone(
            render_story(
                photo,
                theme="atirgul",
                layout=layout,
                price=450_000,
                colour="qizil",
                shop_name=SHOP,
                logo=logo,
            ).jpeg,
            f"logo-story-{layout}.jpg",
        )
        for layout in ("frame", "magazine")
    ]
    index.append(
        "<h2>With the shop's own logo (a SAMPLE logo; each shop sends its own with /logo)</h2>"
        "<div class='stories'>"
        + "".join(
            f"<figure><img src='{src}' alt='logo sample' loading='lazy'></figure>" for src in shots
        )
        + "</div>"
    )
    (OUT / "index.html").write_text(page("CP23 gallery", "".join(index)), encoding="utf-8")

    def summary(values: list[float]) -> dict[str, float]:
        return {
            "count": len(values),
            "min_ms": round(min(values) * 1000, 1),
            "median_ms": round(statistics.median(values) * 1000, 1),
            "max_ms": round(max(values) * 1000, 1),
        }

    TIMINGS.write_text(
        json.dumps(
            {
                "what": "full-size renders by the real code: post 1280 px longest side from a "
                "900x1200 photo, story 1080x1920; cold = first layout of a theme (its motif "
                "rasterised), warm = the rest (motif cached). JPEG encode included.",
                "machine": f"{platform.system()} {platform.machine()}, {platform.processor()}",
                "post": {
                    "cold": summary(timings["post_cold"]),
                    "warm": summary(timings["post_warm"]),
                },
                "story": {
                    "cold": summary(timings["story_cold"]),
                    "warm": summary(timings["story_warm"]),
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(TIMINGS.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
