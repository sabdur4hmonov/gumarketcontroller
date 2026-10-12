"""Fifteen flower themes: the flowers Uzbekistan's shops actually sell (CP23).

A template is a LAYOUT (layouts.py) applied to a THEME (here): 10 x 15 = 150,
built from data, not 150 hand-copied files. A theme owns everything that is
about the flower -- its palettes (two or three, after real varieties), its
emoji, its line-art motif (assets/motifs/*.svg, drawn for this project), the
hashtags the catalogue already understands, and short wording suited to the
flower and its occasions. Layouts own the arrangement.

Wording is written in Uzbek Latin and Russian; Uzbek Cyrillic is derived
(script.py) so the two Uzbek scripts never drift apart.

Detection: CP22 extraction yields canonical lexicon keys (`Fields.flowers`);
`theme_for` turns them into one theme. Two or more different flowers are a
mixed bouquet; flowers in a box are the box theme whatever they are.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .script import to_cyrillic

#: The caption languages a template can be written in.
LANGS = ("uz", "uz_cyrl", "ru")


@dataclass(frozen=True)
class Palette:
    """Colours for one variety. `ink` is read on `bg`; `accent` draws motifs."""

    name: str
    colours: tuple[str, ...]
    bg: str
    ink: str
    accent: str
    soft: str


@dataclass(frozen=True)
class FlowerTheme:
    id: str
    names: tuple[str, str]  # uz Latin, ru (nominative, for labels)
    emoji: tuple[str, ...]
    motif: str
    palettes: tuple[Palette, ...]
    hashtags: tuple[str, ...]
    lines_uz: tuple[str, str, str]
    lines_ru: tuple[str, str, str]

    def name(self, lang: str) -> str:
        if lang == "ru":
            return self.names[1]
        return to_cyrillic(self.names[0]) if lang == "uz_cyrl" else self.names[0]

    def lines(self, lang: str) -> tuple[str, ...]:
        if lang == "ru":
            return self.lines_ru
        if lang == "uz_cyrl":
            return tuple(to_cyrillic(line) for line in self.lines_uz)
        return self.lines_uz

    def palette_for(self, colour: str) -> Palette:
        """The variety matching the bouquet's colour, else the theme's first."""
        for palette in self.palettes:
            if colour in palette.colours:
                return palette
        return self.palettes[0]


def _p(name: str, colours: str, bg: str, ink: str, accent: str, soft: str) -> Palette:
    return Palette(name, tuple(colours.split()), bg, ink, accent, soft)


THEMES: dict[str, FlowerTheme] = {
    theme.id: theme
    for theme in (
        FlowerTheme(
            "atirgul",
            ("Atirgul", "Розы"),
            ("🌹", "❤️", "✨"),
            "atirgul",
            (
                _p("qizil", "qizil toqqizil qora", "#7a1424", "#fff5f5", "#f0b6bd", "#fbeaec"),
                _p("oq", "oq krem", "#fbf7f2", "#3d2b2b", "#b08d57", "#ffffff"),
                _p(
                    "pushti",
                    "pushti ochpushti shaftoli",
                    "#f6d6dc",
                    "#5a1f2e",
                    "#c2456a",
                    "#fff0f3",
                ),
            ),
            ("atirgul", "buket"),
            (
                "Sevgingizni so'zsiz izhor qiling",
                "Yubiley va unutilmas sanalar uchun",
                "Har bir gulbargda mehr bor",
            ),
            (
                "Скажите о любви без слов",
                "Для годовщин и важных дат",
                "В каждом лепестке — нежность",
            ),
        ),
        FlowerTheme(
            "kust_atirgul",
            ("Kust atirgul", "Кустовые розы"),
            ("🌹", "🌿", "💗"),
            "kust_atirgul",
            (
                _p("pushti", "pushti ochpushti qizil", "#fde4ea", "#6b2340", "#d9668b", "#fff5f8"),
                _p("shaftoli", "shaftoli krem sariq", "#fff1e6", "#5b3a29", "#e39b6f", "#fffaf5"),
                _p("oq", "oq binafsha", "#f3eef8", "#3f2d56", "#9b7bc0", "#fbf9fd"),
            ),
            ("kustatirgul", "atirgul", "buket"),
            (
                "Bir shoxda o'nlab kichik atirgullar",
                "Nozik va hajmdor guldasta",
                "Tug'ilgan kun uchun yoqimli sovg'a",
            ),
            (
                "Десятки маленьких роз на одной ветке",
                "Нежный и пышный букет",
                "Приятный подарок на день рождения",
            ),
        ),
        FlowerTheme(
            "lola",
            ("Lola", "Тюльпаны"),
            ("🌷", "🌱", "☀️"),
            "lola",
            (
                _p("bahor", "qizil sariq aralash", "#fff4d6", "#5c3d00", "#e0452f", "#fffbee"),
                _p(
                    "pushti",
                    "pushti ochpushti binafsha",
                    "#ffe3ec",
                    "#6d1d3c",
                    "#e8578a",
                    "#fff4f7",
                ),
                _p("oq", "oq yashil krem", "#eef6ec", "#24432a", "#5a9a5e", "#f8fcf7"),
            ),
            ("tyulpan", "lola", "buket"),
            (
                "Bahor kayfiyatini hadya qiling",
                "8-Mart uchun eng yaxshi tanlov",
                "Yangi uyg'ongan bahor ranglari",
            ),
            (
                "Подарите весеннее настроение",
                "Лучший выбор к 8 Марта",
                "Свежие краски весны",
            ),
        ),
        FlowerTheme(
            "xrizantema",
            ("Xrizantema", "Хризантемы"),
            ("🌼", "🍂", "🤍"),
            "xrizantema",
            (
                _p("kuz", "sariq shaftoli qizil", "#fbe9d0", "#4a2c0b", "#c9731d", "#fff7ec"),
                _p("oq", "oq krem yashil", "#f7f7f2", "#2f3a2f", "#8aa37b", "#ffffff"),
                _p("binafsha", "binafsha pushti", "#efe4f3", "#3b1f4a", "#8e4fa6", "#faf5fc"),
            ),
            ("xrizantema", "buket"),
            (
                "Kuz faslining iliq ranglari",
                "Hurmat va ehtirom ramzi",
                "Uzoq turadigan chiroyli guldasta",
            ),
            (
                "Тёплые краски осени",
                "Символ уважения и почтения",
                "Долго радует свежестью",
            ),
        ),
        FlowerTheme(
            "gerbera",
            ("Gerbera", "Герберы"),
            ("🌻", "😊", "🌈"),
            "gerbera",
            (
                _p("quyosh", "sariq aralash", "#fff3c4", "#4d3a00", "#e09a00", "#fffbe6"),
                _p("marjon", "shaftoli qizil", "#ffe1d6", "#5e1f0f", "#f06a43", "#fff4ef"),
                _p(
                    "pushti",
                    "pushti ochpushti binafsha",
                    "#ffe0ef",
                    "#5c1840",
                    "#e2479a",
                    "#fff4fa",
                ),
            ),
            ("gerbera", "buket"),
            (
                "Quyoshdek yorqin tabassum",
                "Kayfiyatni ko'taradigan ranglar",
                "Do'stlar va hamkasblar uchun",
            ),
            (
                "Яркая, как солнце, улыбка",
                "Цвета, которые поднимают настроение",
                "Для друзей и коллег",
            ),
        ),
        FlowerTheme(
            "liliya",
            ("Liliya", "Лилии"),
            ("🤍", "✨", "🌿"),
            "liliya",
            (
                _p("oq", "oq krem yashil", "#f8f6f0", "#2e3b30", "#8fa37f", "#ffffff"),
                _p("pushti", "pushti ochpushti qizil", "#fbe3e8", "#5a2233", "#d0607a", "#fff5f7"),
                _p("olov", "sariq shaftoli", "#fff0dc", "#5a3410", "#e98a2e", "#fffaf2"),
            ),
            ("nilufar", "liliya", "buket"),
            (
                "Nafis va muattar liliyalar",
                "Poklik va nafosat ramzi",
                "Muhim kunlarga munosib tanlov",
            ),
            (
                "Изящные ароматные лилии",
                "Символ чистоты и изящества",
                "Достойный выбор для важного дня",
            ),
        ),
        FlowerTheme(
            "pion",
            ("Pion", "Пионы"),
            ("🌸", "💞", "🎀"),
            "pion",
            (
                _p("pushti", "pushti ochpushti", "#fde6ea", "#5c1f30", "#e07a93", "#fff6f8"),
                _p("marjon", "shaftoli qizil toqqizil", "#ffe3d8", "#5c2614", "#f07f5c", "#fff5f0"),
                _p("oq", "oq krem", "#fbf6ef", "#3e3227", "#c9a46a", "#ffffff"),
            ),
            ("pion", "buket"),
            (
                "Bahorning eng hashamatli guli",
                "To'y va nikoh kunlari uchun",
                "Yumshoq va hajmdor gulbarglar",
            ),
            (
                "Самый роскошный цветок весны",
                "Для свадьбы и торжеств",
                "Пышные нежные лепестки",
            ),
        ),
        FlowerTheme(
            "gortenziya",
            ("Gortenziya", "Гортензии"),
            ("💙", "☁️", "🌿"),
            "gortenziya",
            (
                _p("kok", "kok binafsha", "#e3edf8", "#1d3557", "#4f7cc0", "#f5f9fd"),
                _p("pushti", "pushti ochpushti", "#f9e3ee", "#5a2341", "#c76393", "#fff5fa"),
                _p("oq", "oq krem yashil", "#f4f6f2", "#2f3d33", "#7f9a85", "#ffffff"),
            ),
            ("gortenziya", "buket"),
            (
                "Bulutdek yumshoq va hajmdor",
                "Uyga osoyishtalik olib kiradi",
                "Samimiy minnatdorchilik uchun",
            ),
            (
                "Пышная, как облако",
                "Приносит в дом уют",
                "Для искренней благодарности",
            ),
        ),
        FlowerTheme(
            "eustoma",
            ("Eustoma", "Эустомы"),
            ("💜", "🌿", "✨"),
            "eustoma",
            (
                _p("binafsha", "binafsha kok", "#efe6f6", "#3d2552", "#9867c5", "#faf6fd"),
                _p("oq", "oq yashil krem", "#f3f7f1", "#26402d", "#6f9c77", "#ffffff"),
                _p("pushti", "pushti ochpushti", "#fbe4ec", "#5b2238", "#cf6b8f", "#fff5f8"),
            ),
            ("eustoma", "buket"),
            (
                "Atirgulga o'xshash nozik gul",
                "Uzoq turadi, nafis ko'rinadi",
                "Har qanday sana uchun nozik tanlov",
            ),
            (
                "Нежный цветок, похожий на розу",
                "Долго стоит и изящно выглядит",
                "Нежный выбор на любую дату",
            ),
        ),
        FlowerTheme(
            "chinnigul",
            ("Chinnigul", "Гвоздики"),
            ("❤️", "🎖️", "🌺"),
            "chinnigul",
            (
                _p("qizil", "qizil toqqizil", "#7d1a1a", "#fff4f0", "#f2b8a8", "#fdecea"),
                _p(
                    "pushti",
                    "pushti ochpushti shaftoli",
                    "#fde3e7",
                    "#5a1e2b",
                    "#d95a72",
                    "#fff5f7",
                ),
                _p("oq", "oq krem", "#f8f5f0", "#33302a", "#b49a6c", "#ffffff"),
            ),
            ("chinnigul", "buket"),
            (
                "Hurmat va xotira ramzi",
                "Ustozlar va faxriylar uchun",
                "Kamtar, ammo uzoq turadigan gul",
            ),
            (
                "Символ уважения и памяти",
                "Для учителей и ветеранов",
                "Скромный, но стойкий цветок",
            ),
        ),
        FlowerTheme(
            "orxideya",
            ("Orxideya", "Орхидеи"),
            ("🌺", "💜", "✨"),
            "orxideya",
            (
                _p(
                    "binafsha", "binafsha toqqizil qora", "#2d1838", "#f8eefc", "#c99be0", "#f6eefa"
                ),
                _p("oq", "oq krem yashil", "#f7f5f8", "#35283d", "#a47fb8", "#ffffff"),
                _p("pushti", "pushti ochpushti", "#fbe4f1", "#5a1f45", "#d65fa3", "#fff5fa"),
            ),
            ("orxideya", "buket"),
            (
                "Hashamat va nafosat timsoli",
                "Uzoq yashaydigan noyob sovg'a",
                "Rahbar va hamkorlar uchun",
            ),
            (
                "Воплощение роскоши и изящества",
                "Долговечный редкий подарок",
                "Для руководителей и партнёров",
            ),
        ),
        FlowerTheme(
            "alstromeriya",
            ("Alstromeriya", "Альстромерии"),
            ("🌺", "🧡", "🍃"),
            "alstromeriya",
            (
                _p("olov", "shaftoli sariq qizil", "#fff0e0", "#5a2f0c", "#e7742a", "#fff8f0"),
                _p("pushti", "pushti ochpushti", "#fde6ee", "#5a2238", "#da6a95", "#fff5f9"),
                _p("binafsha", "binafsha oq", "#f1e9f7", "#3c2753", "#9a73c4", "#fbf8fd"),
            ),
            ("alstromeriya", "buket"),
            (
                "Do'stlik va samimiyat guli",
                "Ikki haftagacha yangi turadi",
                "Rang-barang va quvnoq guldasta",
            ),
            (
                "Цветок дружбы и искренности",
                "Стоит свежим до двух недель",
                "Яркий и весёлый букет",
            ),
        ),
        FlowerTheme(
            "mimoza",
            ("Mimoza", "Мимоза"),
            ("💛", "🌼", "☀️"),
            "mimoza",
            (
                _p("oltin", "sariq", "#fff8d2", "#4f4100", "#d8b000", "#fffdf0"),
                _p("yashil", "yashil aralash", "#eef5e4", "#2f4019", "#8a9a1f", "#f8fbf3"),
                _p("krem", "krem oq", "#fffaf0", "#4a3b12", "#cfa52f", "#ffffff"),
            ),
            ("mimoza", "8mart"),
            (
                "Bahor xabarchisi — mimoza",
                "8-Mart uchun quyoshdek sovg'a",
                "Mayin va xushbo'y sariq gullar",
            ),
            (
                "Мимоза — вестница весны",
                "Солнечный подарок к 8 Марта",
                "Нежные душистые жёлтые цветы",
            ),
        ),
        FlowerTheme(
            "aralash",
            ("Aralash buket", "Сборный букет"),
            ("💐", "🌈", "✨"),
            "aralash",
            (
                _p("rangdor", "aralash qizil sariq", "#fff4e8", "#4a2c1d", "#e3664d", "#fffaf4"),
                _p(
                    "pastel",
                    "pushti binafsha ochpushti kok",
                    "#f6eef7",
                    "#47304f",
                    "#b07cc6",
                    "#fcf8fd",
                ),
                _p("yashil", "yashil oq krem shaftoli", "#eef6ee", "#22402a", "#4f9a64", "#f8fcf8"),
            ),
            ("buket",),
            (
                "Bir guldastada butun bir bahor",
                "Har qanday bayramga mos",
                "Turli gullar uyg'unligi",
            ),
            (
                "Целая весна в одном букете",
                "Подходит к любому празднику",
                "Гармония разных цветов",
            ),
        ),
        FlowerTheme(
            "quti",
            ("Qutidagi gullar", "Цветы в коробке"),
            ("🎁", "💝", "🌸"),
            "quti",
            (
                _p("qora-oltin", "qora toqqizil qizil", "#1f1b1a", "#f7ecd8", "#d4af6a", "#f5ecdc"),
                _p(
                    "pushti",
                    "pushti ochpushti shaftoli",
                    "#fbe5ea",
                    "#5a2131",
                    "#c96a83",
                    "#fff5f7",
                ),
                _p("oq", "oq krem sariq", "#f9f5ee", "#3d3326", "#b8955a", "#ffffff"),
            ),
            ("korobka", "buket"),
            (
                "Qutidagi gullar — tayyor sovg'a",
                "Vaza kerak emas, uzoq turadi",
                "Hashamatli taqdim etish uchun",
            ),
            (
                "Цветы в коробке — готовый подарок",
                "Не нужна ваза, долго стоят",
                "Для роскошного вручения",
            ),
        ),
    )
}

#: Lexicon key -> its theme. Keys absent here are flowers without a theme of
#: their own (gipsofila, frezia, ...): on their own they are a mixed bouquet.
FLOWER_THEME = {
    "atirgul": "atirgul",
    "kustatirgul": "kust_atirgul",
    "tyulpan": "lola",
    "xrizantema": "xrizantema",
    "gerbera": "gerbera",
    "nilufar": "liliya",
    "pion": "pion",
    "gortenziya": "gortenziya",
    "eustoma": "eustoma",
    "chinnigul": "chinnigul",
    "orxideya": "orxideya",
    "alstromeriya": "alstromeriya",
    "mimoza": "mimoza",
}
#: Words in `Fields.flowers` that are not a flower: the form, not the content.
NOT_A_FLOWER = {"buket"}

#: A box is packaging, not a flower (CP22 keeps "quti" out of the lexicon on
#: purpose), so it is read from the owner's own words: flowers in a box are the
#: box theme whatever the flowers are.
_BOX = re.compile(
    r"(?<![^\W\d_])(?:quti\w*|korobka\w*|коробк\w*|коробочк\w*|қути\w*|flowerbox|box)"
    r"(?![^\W\d_])",
    re.IGNORECASE,
)

#: Display names of every lexicon flower key, for titles: (uz Latin, ru).
FLOWER_NAMES = {
    "atirgul": ("atirgul", "розы"),
    "kustatirgul": ("kust atirgul", "кустовые розы"),
    "tyulpan": ("lola", "тюльпаны"),
    "xrizantema": ("xrizantema", "хризантемы"),
    "chinnigul": ("chinnigul", "гвоздики"),
    "pion": ("pion", "пионы"),
    "nilufar": ("liliya", "лилии"),
    "gerbera": ("gerbera", "герберы"),
    "buket": ("guldasta", "букет"),
    "eustoma": ("eustoma", "эустомы"),
    "gortenziya": ("gortenziya", "гортензии"),
    "orxideya": ("orxideya", "орхидеи"),
    "gipsofila": ("gipsofila", "гипсофила"),
    "alstromeriya": ("alstromeriya", "альстромерии"),
    "frezia": ("frezia", "фрезии"),
    "ranunkulyus": ("ranunkulyus", "ранункулюсы"),
    "lavanda": ("lavanda", "лаванда"),
    "nargis": ("nargis", "нарциссы"),
    "mimoza": ("mimoza", "мимоза"),
}

#: Display names of every lexicon colour key: (uz Latin, ru).
COLOUR_NAMES = {
    "qizil": ("qizil", "красный"),
    "oq": ("oq", "белый"),
    "pushti": ("pushti", "розовый"),
    "sariq": ("sariq", "жёлтый"),
    "kok": ("ko'k", "голубой"),
    "binafsha": ("binafsha", "фиолетовый"),
    "yashil": ("yashil", "зелёный"),
    "qora": ("qora", "чёрный"),
    "toqqizil": ("to'q qizil", "бордовый"),
    "ochpushti": ("och pushti", "нежно-розовый"),
    "krem": ("krem", "кремовый"),
    "shaftoli": ("shaftoli", "персиковый"),
    "aralash": ("aralash", "разноцветный"),
}


def localized(pair: tuple[str, str], lang: str) -> str:
    """A (uz Latin, ru) pair in `lang`."""
    if lang == "ru":
        return pair[1]
    return to_cyrillic(pair[0]) if lang == "uz_cyrl" else pair[0]


def in_a_box(text: str) -> bool:
    return _BOX.search(text.replace("’", "").replace("'", "")) is not None


def theme_for(flowers: list[str], text: str = "") -> str:
    """The one theme for what extraction found in the owner's words."""
    if in_a_box(text):
        return "quti"
    real = [flower for flower in dict.fromkeys(flowers) if flower not in NOT_A_FLOWER]
    if len(real) == 1 and real[0] in FLOWER_THEME:
        return FLOWER_THEME[real[0]]
    return "aralash"
