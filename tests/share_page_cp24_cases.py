"""Bounded sample content for CP24 HTTP, browser checks and evidence (no DB rows)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from gulbot.models.share_page import PAGE_TEMPLATES
from gulbot.web import render
from gulbot.web.designs_cp24 import CP24_DESIGNS

ALL_DESIGNS = (*PAGE_TEMPLATES, *CP24_DESIGNS)
HOSTILE = '<script>alert(1)</script><img src=x onerror=alert(2)>"&'


def case_html(theme: str, kind: str, lang: str, *, worst: bool = False) -> str:
    page = render.sample_page(kind, theme, lang)
    page.seal_monogram = "ҚҒҲЎ" if lang == "uz_cyrl" else "A&M"
    page.music = "bahor"
    page.show_countdown = True
    page.show_gallery = True
    page.wishes_enabled = True
    page.dress_code = {
        "uz": "Bayramona libos",
        "uz_cyrl": "Байрамона либос",
        "ru": "Праздничная одежда",
        "en": "Festive attire",
    }[lang]
    page.dress_colors = "oq,pushti,yashil,oltin,kok"
    page.program = "18:00 Kutib olish\n19:00 Bayram dasturi"
    page.contact = "Gulzor"
    if worst:
        page.seal_monogram = "ҚҒҲЎҚ" if lang == "uz_cyrl" else "WWWWW"
        # Full field limits, with an unbroken word and hostile markup; testing
        # scrolling document width alone would conceal overflow behind body clipping.
        word = "Қғҳў" if lang in ("uz_cyrl", "ru") else "Wxyz"
        page.question = (HOSTILE + word * 40)[:140]
        page.message = (HOSTILE + word * 120)[:400]
        page.name_1 = (HOSTILE + word * 20)[:60]
        page.name_2 = word * 15
        page.venue = (HOSTILE + word * 50)[:160]
        page.title = (HOSTILE + word * 25)[:80]
        page.closing = (HOSTILE + word * 60)[:200]
        page.dress_code = word * 30
        page.contact = word * 30
        page.program = (
            "\n".join(f"1{n}:00 " + word * 11 for n in range(7)) + "\n" + (word * 11)[:43]
        )
    photos = [render.PhotoLink(f"/static/cp24/sample-{n}.svg", 480, 600) for n in (1, 2, 3)]
    wishes: list[Any] = [
        SimpleNamespace(
            body="Қ ғ ҳ ў — " + ("W" * 290 if worst else "Baxtli kunlar tilaymiz!"),
            author="W" * 40 if worst else "Do'stlar",
        )
    ]
    branding = render.Branding("W" * 80 if worst else "Gulzor", "/demo/none/go")
    return render.page_html(
        page,
        branding,
        tz_name="Asia/Tashkent",
        base="/demo/none",
        plan=render.sample_plan(lang) if kind == "yesno" else None,
        photos=photos,
        wishes=wishes,
    )
