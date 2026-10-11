"""Original Latin-Uzbek captions with a stable CP7/CP8 catalog header."""

from __future__ import annotations

from html import escape

from .extraction import Fields

CAPTION_STYLES = {
    "classic": ("🌹 Siz uchun yangi guldasta", "Gullar", "Do'kon", "Buyurtma uchun yozing"),
    "minimal": ("", "", "", ""),
    "premium": ("✦ Nafis tanlov", "Tarkibi", "Taqdim etadi", "Go'zallikni hadya qiling"),
    "festive": ("🎉 Bayram kayfiyati!", "Bayram gullari", "Manzil", "Quvonch ulashing"),
    "playful": ("🌈 Bir quchoq tabassum", "Ichida", "Biz", "Kimni xursand qilamiz?"),
    "compact": ("🌷 Bugungi tanlov", "", "", "Hoziroq yozing"),
    "sale": ("🛍 Sizga munosib tanlov", "Guldasta", "Do'kon", "Buyurtma bering"),
    "romantic": ("💕 Tuyg'ular gullarda", "Sevgi ranglari", "Gul manzili", "Yaqiningizga atalgan"),
    "elegant": ("❧ Nafosat va uyg'unlik", "Gul tarkibi", "Taqdimot", "Mehr bilan tanlangan"),
    "friendly": ("😊 Salom, gul ishqibozi!", "Bizning gullar", "Bizdan", "Sizni kutamiz"),
    "modern": ("◼ Yangi kayfiyat", "Kompozitsiya", "Studio", "Tanlang. Yozing. Hadya qiling."),
    "checklist": ("✅ Guldasta ma'lumotlari", "✓ Tarkib", "✓ Do'kon", "✓ Buyurtma: xabarda"),
    "catalogue": ("📋 Gul katalogi", "Tur va rang", "Sotuvchi", "Batafsil: bizga yozing"),
    "gift": ("🎁 Mehringiz uchun sovg'a", "Sovg'a gullari", "Tayyorlagan", "Esda qoladigan lahza"),
    "spotlight": ("✨ Diqqat markazida", "Bugunning gullari", "Tanlov", "Guldastani tanlang"),
    "poetic": ("🍃 Har yaproqda bir tilak", "Gul ohangi", "Gul maskani", "Mehr gullab yashnasin"),
    "geometric": ("◆ Ranglar uyg'unligi", "◇ Gullar", "◇ Do'kon", "◆ Buyurtma uchun yozing"),
    "pastel": ("🌸 Mayin lahzalar", "Mayin gullar", "Gul do'koni", "Iliq tuyg'ular hadyasi"),
    "monochrome": ("● Oddiylikda go'zallik", "Tarkib", "Do'kon", "Sizning tanlovingiz"),
    "signature": ("✍ Mehr bilan yaratilgan", "Guldasta imzosi", "Muallif", "Gullar orqali ayting"),
}
CAPTION_LABELS = dict(
    zip(
        CAPTION_STYLES,
        (
            "Klassik",
            "Sodda",
            "Nafis",
            "Bayramona",
            "Quvnoq",
            "Qisqa",
            "Taklif",
            "Romantik",
            "Elegant",
            "Samimiy",
            "Zamonaviy",
            "Ro'yxat",
            "Katalog",
            "Sovg'a",
            "Diqqat markazida",
            "She'riy",
            "Geometrik",
            "Pastel",
            "Oq-qora",
            "Do'kon imzosi",
        ),
        strict=True,
    )
)


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def escaped_fit(text: str, budget: int) -> str:
    output: list[str] = []
    used = 0
    for char in text:
        part = escape(char, quote=False)
        cost = utf16_length(part)
        if used + cost > budget:
            break
        output.append(part)
        used += cost
    return "".join(output)


def caption(fields: Fields, *, style: str, shop_name: str) -> str:
    fields.validate()
    if style not in CAPTION_STYLES:
        raise ValueError("unknown caption style")
    heading, flower_label, shop_label, closing = CAPTION_STYLES[style]
    # A controlled first line makes CP8's product_name stable. Owner strings
    # follow the labelled price so another price in the description cannot win.
    title = f"{', '.join(fields.flowers).capitalize()} buketi — {fields.count} dona"
    price = f"Narxi: {fields.price:,} so'm".replace(",", " ")
    tags = " ".join(f"#{f}" for f in fields.flowers) + " #buket"
    details = f"{flower_label + ': ' if flower_label else ''}{fields.colour} · {fields.count} dona"
    fixed = [title, price, heading, details, closing, tags]
    fixed_cost = utf16_length("\n".join(line for line in fixed if line)) + 4
    shop = escaped_fit(f"{shop_label + ': ' if shop_label else ''}{shop_name}", 160)
    description = escaped_fit(fields.description, 1024 - fixed_cost - utf16_length(shop))
    # Layout varies below the stable catalog header, with no shuffled monetary
    # line. Each style has its own tone, labels, ornaments and closing.
    body = [heading, details, shop, description, closing]
    if style in {"premium", "elegant", "signature", "poetic"}:
        body = [heading, description, details, closing, shop]
    elif style in {"catalogue", "checklist", "compact", "minimal"}:
        body = [details, description, shop, heading, closing]
    return "\n".join(line for line in [title, price, *body, tags] if line)
