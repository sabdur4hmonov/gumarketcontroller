"""Instagram Story images (CP23 phase 2): 10 story layouts x 15 flower themes.

1080 x 1920, from the announcement's first photo, with the flower's name,
the price and the shop. Instagram covers roughly the top 250 px (progress
bar, account) and the bottom 340 px (reply box, buttons) of a story, so
EVERY text container lies inside SAFE -- the tests check each recorded box.
Decoration (motifs, frames, the photo) may use the whole canvas.

The same theme system as posts: palettes, motifs, wording come from
themes.py; the text fitting and the contrast rule from designs.py. `scale`
renders the same design smaller, for the picker's previews.

No Meta API is involved: the owner downloads the image and shares it to
Stories from the phone. Phase 3 (instagram.py) can publish it when enabled.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageOps

from .designs import Canvas, Rendered, Texts, encode, open_photo, text_on
from .flower_templates import money
from .script import to_cyrillic
from .themes import THEMES, FlowerTheme, Palette

WIDTH, HEIGHT = 1080, 1920
#: Instagram's covered zones: text stays between these.
SAFE_TOP, SAFE_BOTTOM = 250, 1580
SIDE = 40
SAFE = (SIDE, SAFE_TOP, WIDTH - SIDE, SAFE_BOTTOM)
#: The picker's ten previews: 270 x 480, the same design scaled.
STORY_PREVIEW_SCALE = 0.25


@dataclass(frozen=True)
class StoryLayout:
    id: str
    label: tuple[str, str]  # uz Latin, ru

    def name(self, lang: str) -> str:
        if lang == "ru":
            return self.label[1]
        return to_cyrillic(self.label[0]) if lang == "uz_cyrl" else self.label[0]


class Story:
    """A story canvas in 1080x1920 design units, drawn at `scale`."""

    def __init__(self, photo: Image.Image, scale: float) -> None:
        self.s = scale
        self.photo = photo
        self.canvas = Canvas(Image.new("RGB", (self.px(WIDTH), self.px(HEIGHT)), "#ffffff"))

    def px(self, value: float) -> int:
        return round(value * self.s)

    def box(self, x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return (self.px(x0), self.px(y0), self.px(x1), self.px(y1))

    def fill(self, colour: str) -> None:
        self.canvas.panel((0, 0, self.px(WIDTH), self.px(HEIGHT)), colour)

    def cover(self, x0: float, y0: float, x1: float, y1: float, mask: str = "") -> None:
        """The photo, cropped to fill the box from its centre; optionally masked."""
        box = self.box(x0, y0, x1, y1)
        size = (box[2] - box[0], box[3] - box[1])
        part = ImageOps.fit(self.photo, size, Image.Resampling.LANCZOS)
        if not mask:
            self.canvas.image.paste(part, box[:2])
            return
        alpha = Image.new("L", size, 0)
        draw = ImageDraw.Draw(alpha)
        if mask == "circle":
            draw.ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)
        else:  # arch: a semicircle on a rectangle
            r = size[0] // 2
            draw.ellipse((0, 0, size[0] - 1, 2 * r), fill=255)
            draw.rectangle((0, r, size[0] - 1, size[1] - 1), fill=255)
        self.canvas.image.paste(part, box[:2], alpha)

    def panel(self, colour: str, x0: float, y0: float, x1: float, y1: float, r: float = 0) -> None:
        self.canvas.panel(self.box(x0, y0, x1, y1), colour, radius=self.px(r))

    def motif(self, name: str, cx: float, cy: float, size: float, colour: str) -> None:
        self.canvas.motif(name, (self.px(cx), self.px(cy)), self.px(size), colour)

    def stack(
        self,
        colour: str,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        rows: list[tuple[str, str, float, bool]],
        align: str = "center",
    ) -> None:
        self.canvas.stack(self.box(x0, y0, x1, y1), rows, colour, align=align)


def _flourish(st: Story, p: Palette) -> None:
    """Decoration for the bottom zone Instagram covers: no text goes there."""
    for cx, size in ((360, 150), (540, 190), (720, 150)):
        st.motif("sprig", cx, 1745, size, p.accent)


def _rows(x: Texts) -> list[tuple[str, str, float, bool]]:
    return [
        ("name", x.name, 0.26, False),
        ("price", x.price, 0.44, True),
        ("shop", x.shop, 0.3, False),
    ]


StoryDraw = Callable[[Story, FlowerTheme, Palette, Texts], None]


def _frame(st: Story, t: FlowerTheme, p: Palette, x: Texts) -> None:
    st.fill(p.bg)
    _flourish(st, p)
    st.cover(70, 70, 1010, 1270)
    st.canvas.draw.rectangle(st.box(70, 70, 1010, 1270), outline=p.accent, width=st.px(8))
    st.motif(t.motif, 150, 1210, 170, p.accent)
    st.stack(text_on(p, p.bg), 100, 1310, 980, 1560, _rows(x))


def _split(st: Story, t: FlowerTheme, p: Palette, x: Texts) -> None:
    st.cover(0, 0, 1080, 1140)
    st.panel(p.bg, 0, 1140, 1080, 1920)
    st.canvas.draw.line(st.box(0, 1140, 1080, 1140), fill=p.accent, width=st.px(10))
    st.motif(t.motif, 880, 1340, 300, p.accent)
    st.stack(text_on(p, p.bg), 80, 1190, 720, 1550, _rows(x), align="left")


def _polaroid(st: Story, t: FlowerTheme, p: Palette, x: Texts) -> None:
    st.fill(p.bg)
    _flourish(st, p)
    for cx in (160, 540, 920):
        st.motif("sparkle", cx, 150, 90, p.accent)
    st.panel(p.soft, 110, 280, 970, 1560, r=14)
    st.cover(150, 320, 930, 1200)
    st.motif(t.motif, 860, 1260, 110, p.accent)
    st.stack(text_on(p, p.soft), 160, 1230, 800, 1540, _rows(x), align="left")


def _arch(st: Story, t: FlowerTheme, p: Palette, x: Texts) -> None:
    st.fill(p.bg)
    _flourish(st, p)
    st.motif(t.motif, 540, 150, 170, p.accent)
    st.cover(150, 260, 930, 1220, mask="arch")
    st.motif("sprig", 120, 1260, 160, p.accent)
    st.motif("sprig", 960, 1260, 160, p.accent)
    st.stack(text_on(p, p.bg), 150, 1270, 930, 1560, _rows(x))


def _circle(st: Story, t: FlowerTheme, p: Palette, x: Texts) -> None:
    st.fill(p.soft)
    _flourish(st, p)
    st.canvas.draw.ellipse(st.box(100, 320, 980, 1200), fill=p.accent)
    st.cover(120, 340, 960, 1180, mask="circle")
    for cx, cy in ((150, 330), (930, 330), (150, 1190), (930, 1190)):
        st.motif(t.motif, cx, cy, 150, p.accent)
    st.stack(text_on(p, p.soft), 120, 1250, 960, 1560, _rows(x))


def _minimal(st: Story, t: FlowerTheme, p: Palette, x: Texts) -> None:
    st.cover(0, 0, 1080, 1920)
    st.panel(p.bg, 90, 1290, 990, 1570, r=60)
    st.motif(t.motif, 200, 1430, 180, p.accent)
    st.stack(text_on(p, p.bg), 310, 1320, 950, 1540, _rows(x), align="left")


def _tag(st: Story, t: FlowerTheme, p: Palette, x: Texts) -> None:
    st.cover(0, 0, 1080, 1920)
    st.canvas.draw.line(st.box(760, 0, 760, 1060), fill=p.accent, width=st.px(6))
    st.panel(p.bg, 480, 1040, 1000, 1570, r=40)
    st.canvas.draw.ellipse(st.box(735, 1065, 785, 1115), fill=p.accent)
    st.motif(t.motif, 560, 1180, 120, p.accent)
    st.stack(text_on(p, p.bg), 520, 1250, 960, 1550, _rows(x))


def _burst(st: Story, t: FlowerTheme, p: Palette, x: Texts) -> None:
    st.canvas.boost = {"price": 1.2}
    st.cover(0, 0, 1080, 1920)
    st.canvas.draw.ellipse(
        st.box(170, 840, 910, 1580), fill=p.bg, outline=p.accent, width=st.px(10)
    )
    st.motif(t.motif, 540, 960, 150, p.accent)
    st.stack(text_on(p, p.bg), 250, 1050, 830, 1420, _rows(x))


def _magazine(st: Story, t: FlowerTheme, p: Palette, x: Texts) -> None:
    st.canvas.boost = {"name": 2.2, "price": 1.2}
    st.panel(p.bg, 0, 0, 1080, 640)
    st.cover(0, 640, 1080, 1920)
    st.motif(t.motif, 930, 450, 220, p.accent)
    st.canvas.stack(
        st.box(80, 270, 800, 590),
        [("name", x.name, 0.62, True), ("shop", x.shop, 0.38, False)],
        text_on(p, p.bg),
    )
    st.panel(p.ink, 70, 1390, 760, 1560, r=24)
    st.canvas.text(
        "price", x.price, st.box(110, 1420, 720, 1530), text_on(p, p.ink), truncate=False, floor=10
    )


def _duo(st: Story, t: FlowerTheme, p: Palette, x: Texts) -> None:
    st.canvas.boost = {"name": 1.3}
    st.panel(p.bg, 0, 0, 470, 1920)
    st.cover(470, 0, 1080, 1920)
    st.canvas.draw.line(st.box(470, 0, 470, 1920), fill=p.accent, width=st.px(8))
    st.motif(t.motif, 235, 1740, 260, p.accent)
    st.motif("sprig", 235, 150, 200, p.accent)
    st.motif(t.motif, 235, 470, 200, p.accent)
    st.stack(text_on(p, p.bg), 40, 640, 430, 1140, _rows(x), align="left")


STORY_LAYOUTS: dict[str, tuple[StoryLayout, StoryDraw]] = {
    layout.id: (layout, draw)
    for layout, draw in (
        (StoryLayout("frame", ("Ramka", "Рамка")), _frame),
        (StoryLayout("split", ("Ikki qism", "Две части")), _split),
        (StoryLayout("polaroid", ("Polaroid", "Полароид")), _polaroid),
        (StoryLayout("arch", ("Ravoq", "Арка")), _arch),
        (StoryLayout("circle", ("Doira", "Круг")), _circle),
        (StoryLayout("minimal", ("Sodda", "Минимализм")), _minimal),
        (StoryLayout("tag", ("Yorliq", "Бирка")), _tag),
        (StoryLayout("burst", ("Narx nishoni", "Ценник")), _burst),
        (StoryLayout("magazine", ("Jurnal", "Журнал")), _magazine),
        (StoryLayout("duo", ("Ikki rang", "Два цвета")), _duo),
    )
}
STORY_LAYOUT_IDS = tuple(STORY_LAYOUTS)
ALL_STORIES = tuple(f"{theme}.{layout}" for theme in THEMES for layout in STORY_LAYOUT_IDS)


def story_photo(photo: bytes) -> Image.Image:
    image = open_photo(photo)
    image.thumbnail((2000, 2000))
    return image


def render_story(
    photo: bytes | Image.Image,
    *,
    theme: str,
    layout: str,
    price: int,
    colour: str,
    shop_name: str,
    lang: str = "uz",
    scale: float = 1.0,
    logo: Image.Image | None = None,
) -> Rendered:
    """One story image. JPEG at high quality: it is sent as a document."""
    started = time.perf_counter()
    if theme not in THEMES or layout not in STORY_LAYOUTS:
        raise ValueError("unknown story")
    if not 0.1 <= scale <= 1.0:
        raise ValueError("bad scale")
    flower = THEMES[theme]
    palette = flower.palette_for(colour)
    image = story_photo(photo) if isinstance(photo, bytes) else photo
    story = Story(image, scale)
    texts = Texts(
        name=flower.name(lang), price=money(price, lang), shop=" ".join(shop_name.split())[:120]
    )
    _, draw = STORY_LAYOUTS[layout]
    draw(story, flower, palette, texts)
    if logo is not None:
        story.canvas.stamp(logo, story.box(*STORY_LOGO_SLOT[layout]), palette.soft)
    jpeg = encode(story.canvas.image, quality=92 if scale == 1.0 else 85)
    w, h = story.canvas.size
    return Rendered(
        jpeg, w, h, story.canvas.boxes, time.perf_counter() - started, story.canvas.logo_box
    )


#: Where each story layout puts the shop's logo: inside the visible zone,
#: clear of every text block (design units).
STORY_LOGO_SLOT: dict[str, tuple[int, int, int, int]] = {
    "frame": (840, 270, 990, 420),
    "split": (890, 270, 1050, 430),
    "polaroid": (780, 340, 910, 470),
    "arch": (30, 270, 170, 410),
    "circle": (470, 262, 610, 402),
    "minimal": (880, 270, 1040, 430),
    "tag": (40, 270, 200, 430),
    "burst": (40, 270, 200, 430),
    "magazine": (890, 680, 1040, 830),
    "duo": (130, 1250, 340, 1460),
}
