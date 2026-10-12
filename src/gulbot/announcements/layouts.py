"""Ten layouts: how a post is arranged, whatever the flower (CP23).

A layout owns the ARRANGEMENT -- its caption's order of parts and its tone
words, and the shape of its overlay on the photo (designs.py). The flower
theme (themes.py) supplies colours, motif, emoji and wording. Template id:
"<theme>.<layout>", for example "lola.festive" (a dot, because ":" separates
callback fields).

Text is written in Uzbek Latin and Russian; Uzbek Cyrillic is derived.
"""

from __future__ import annotations

from dataclasses import dataclass

from .script import to_cyrillic


@dataclass(frozen=True)
class Layout:
    id: str
    label: tuple[str, str]  # picker label: uz Latin, ru
    heading: tuple[str, str]  # caption heading ("" = none)
    closing: tuple[str, str]
    badge: tuple[str, str]  # a short word drawn on the image ("" = none)
    mark: str  # the heading's ornament
    #: Which theme line the caption uses (0-2), so ten layouts are not ten
    #: copies of the same sentence.
    line: int
    #: Caption parts after the fixed catalog header, in order.
    order: tuple[str, ...]

    def text(self, pair: tuple[str, str], lang: str) -> str:
        if lang == "ru":
            return pair[1]
        return to_cyrillic(pair[0]) if lang == "uz_cyrl" else pair[0]


LAYOUTS: dict[str, Layout] = {
    layout.id: layout
    for layout in (
        Layout(
            "classic",
            ("Klassik", "Классика"),
            ("Siz uchun yangi guldasta", "Новый букет для вас"),
            ("Buyurtma uchun yozing", "Пишите для заказа"),
            ("", ""),
            "{e}",
            0,
            ("heading", "line", "details", "description", "shop", "closing"),
        ),
        Layout(
            "minimal",
            ("Sodda", "Минимализм"),
            ("", ""),
            ("", ""),
            ("", ""),
            "",
            2,
            ("details", "description", "shop"),
        ),
        Layout(
            "festive",
            ("Bayramona", "Праздничный"),
            ("Bayram muborak!", "С праздником!"),
            ("Quvonch ulashing", "Дарите радость"),
            ("", ""),
            "🎉{e}",
            1,
            ("heading", "line", "details", "description", "shop", "closing"),
        ),
        Layout(
            "premium",
            ("Premium", "Премиум"),
            ("Nafis tanlov", "Изысканный выбор"),
            ("Go'zallikni hadya qiling", "Дарите красоту"),
            ("", ""),
            "✦",
            0,
            ("heading", "line", "description", "details", "closing", "shop"),
        ),
        Layout(
            "playful",
            ("Quvnoq", "Весёлый"),
            ("Bir quchoq tabassum", "Охапка улыбок"),
            ("Kimni xursand qilamiz?", "Кого порадуем?"),
            ("", ""),
            "{e}{e2}",
            2,
            ("heading", "line", "details", "description", "closing", "shop"),
        ),
        Layout(
            "sale",
            ("Qisqa taklif", "Короткое предложение"),
            ("Bugungi taklif", "Предложение дня"),
            ("Hoziroq yozing", "Пишите прямо сейчас"),
            ("TAKLIF", "АКЦИЯ"),
            "🔥",
            1,
            ("heading", "details", "shop", "closing", "description"),
        ),
        Layout(
            "gift",
            ("Sovg'a uchun", "Для подарка"),
            ("Sovg'a uchun tayyor", "Готово к подарку"),
            ("Esda qoladigan lahza", "Момент, который запомнится"),
            ("SOVG'A", "ПОДАРОК"),
            "🎁",
            1,
            ("heading", "line", "details", "description", "shop", "closing"),
        ),
        Layout(
            "new_arrival",
            ("Yangi keldi", "Новинка"),
            ("Yangi keldi!", "Новое поступление!"),
            ("Birinchilardan bo'lib tanlang", "Выбирайте первыми"),
            ("YANGI", "НОВИНКА"),
            "🆕",
            0,
            ("heading", "line", "details", "description", "shop", "closing"),
        ),
        Layout(
            "price_first",
            ("Narx oldinda", "Цена в начале"),
            ("Narxi aniq, guli yangi", "Честная цена, свежие цветы"),
            ("Buyurtma uchun yozing", "Пишите для заказа"),
            ("", ""),
            "💰",
            2,
            ("heading", "details", "description", "shop", "closing"),
        ),
        Layout(
            "story_card",
            ("Karta", "Карточка"),
            ("Bugungi guldasta", "Букет дня"),
            ("Sizni kutamiz", "Ждём вас"),
            ("", ""),
            "{e}",
            1,
            ("heading", "rule", "line", "details", "rule", "description", "shop", "closing"),
        ),
    )
}

#: Picker order: the order above.
LAYOUT_IDS = tuple(LAYOUTS)
