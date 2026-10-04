"""What the PUBLIC pages say, in the four languages a page can be made in.

Separate from `gulbot.i18n.catalog`, which is the bot's own uz + ru
conversation with the customer. A page is read by somebody else entirely -- the
person being asked or invited -- so its language is chosen per page, and the
choice includes Uzbek in Cyrillic script and English, which the bot itself does
not speak.

UZBEK CYRILLIC IS GENERATED, not typed twice. `to_cyrillic` applies the standard
Latin -> Cyrillic correspondence to our own fixed strings, and
`tests/test_web_strings.py` pins it against words checked by hand. Where the two
orthographies genuinely differ rather than transliterate -- the month names, which
Cyrillic Uzbek spells the Russian way (Sentabr / Сентябрь) -- the Cyrillic is
written out. User text is NEVER transliterated: a name stays as its owner typed it.
"""

from __future__ import annotations

import re
from typing import Final

#: Page languages, as stored in share_pages.lang.
PAGE_LANGUAGES: Final = ("uz", "uz_cyrl", "ru", "en")

#: The value of <html lang>. Cyrillic Uzbek needs its script subtag: the themes
#: switch display fonts on :lang(uz-Cyrl), because several decorative faces
#: have no қ, ғ or ҳ.
HTML_LANG: Final = {"uz": "uz", "uz_cyrl": "uz-Cyrl", "ru": "ru", "en": "en"}

# --- Latin -> Cyrillic -------------------------------------------------------

_APOSTROPHES = "'‘’ʻʼ`"
_SINGLE = {
    "a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "ҳ", "i": "и",
    "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "қ",
    "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "x": "х", "y": "й", "z": "з",
    "c": "с", "w": "в",
}  # fmt: skip
_TOKEN = re.compile(
    rf"o[{_APOSTROPHES}]|g[{_APOSTROPHES}]|sh|ch|yo(?![{_APOSTROPHES}])|yu|ya|ye|[a-z]|[{_APOSTROPHES}]",
    re.IGNORECASE,
)
_PAIRS = {"sh": "ш", "ch": "ч", "yo": "ё", "yu": "ю", "ya": "я", "ye": "е"}


def _cyr(token: str, *, word_start: bool) -> str:
    low = token.lower()
    if low[0] in "og" and len(low) == 2 and low[1] in _APOSTROPHES:
        out = "ў" if low[0] == "o" else "ғ"
    elif low in _PAIRS:
        out = _PAIRS[low]
    elif low in _APOSTROPHES:
        return "ъ"  # tutuq belgisi: ma'no -> маъно
    elif low == "e" and word_start:
        out = "э"
    else:
        out = _SINGLE[low]
    return out.upper() if token[0].isupper() else out


_PLACEHOLDER = re.compile(r"(\{[a-z_]+\})")


def _cyrillic_run(latin: str) -> str:
    out: list[str] = []
    pos = 0
    for match in _TOKEN.finditer(latin):
        out.append(latin[pos : match.start()])
        previous = latin[match.start() - 1] if match.start() > 0 else " "
        out.append(_cyr(match.group(0), word_start=not previous.isalpha()))
        pos = match.end()
    out.append(latin[pos:])
    return "".join(out)


def to_cyrillic(latin: str) -> str:
    """Uzbek Latin -> Uzbek Cyrillic, for OUR fixed strings only.

    A `{placeholder}` is left exactly as written -- it is filled in later by
    str.format, and a transliterated name would no longer match.
    """
    return "".join(
        part if _PLACEHOLDER.fullmatch(part) else _cyrillic_run(part)
        for part in _PLACEHOLDER.split(latin)
    )


# --- Calendar words -----------------------------------------------------------

MONTHS: Final[dict[str, tuple[str, ...]]] = {
    "uz": ("Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
           "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"),
    "uz_cyrl": ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"),
    # Genitive: the page reads "15 / июня 2027".
    "ru": ("января", "февраля", "марта", "апреля", "мая", "июня",
           "июля", "августа", "сентября", "октября", "ноября", "декабря"),
    "en": ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"),
}  # fmt: skip

WEEKDAYS: Final[dict[str, tuple[str, ...]]] = {
    "uz": ("Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"),
    "ru": ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}
WEEKDAYS["uz_cyrl"] = tuple(to_cyrillic(day) for day in WEEKDAYS["uz"])


# --- Fixed page text ------------------------------------------------------------

_TEXT: Final[dict[str, dict[str, str]]] = {
    "eyebrow": {
        "uz": "Senga bitta savolim bor",
        "ru": "У меня к тебе вопрос",
        "en": "I have a question for you",
    },
    "yes": {"uz": "Ha", "ru": "Да", "en": "Yes"},
    "no": {"uz": "Yo'q", "ru": "Нет", "en": "No"},
    "yay": {"uz": "Hurraa!", "ru": "Ура!", "en": "Yay!"},
    "open": {"uz": "Ochish uchun bosing", "ru": "Нажмите, чтобы открыть", "en": "Tap to open"},
    "cta": {"uz": "Gul buyurtma qilish", "ru": "Заказать цветы", "en": "Order flowers"},
    "made_with": {
        "uz": "Sahifa «{shop}» gul do'koni boti orqali yaratilgan",
        "ru": "Страница создана в боте цветочного магазина «{shop}»",
        "en": "Made with the «{shop}» flower shop bot",
    },
    "days": {"uz": "kun", "ru": "дней", "en": "days"},
    "hours": {"uz": "soat", "ru": "часов", "en": "hours"},
    "minutes": {"uz": "daqiqa", "ru": "минут", "en": "min"},
    "seconds": {"uz": "soniya", "ru": "секунд", "en": "sec"},
    "venue": {"uz": "Manzil", "ru": "Место", "en": "Venue"},
    "dress_code": {"uz": "Kiyinish uslubi", "ru": "Дресс-код", "en": "Dress code"},
    "program": {"uz": "Dastur", "ru": "Программа", "en": "Programme"},
    "contact": {"uz": "Aloqa uchun", "ru": "Контакт", "en": "Contact"},
    "calendar": {"uz": "Kalendarga qo'shish", "ru": "В календарь", "en": "Add to calendar"},
    "rsvp_title": {"uz": "Kelasizmi?", "ru": "Вы придёте?", "en": "Will you come?"},
    "rsvp_yes": {"uz": "Kelaman", "ru": "Приду", "en": "I'll be there"},
    "rsvp_no": {"uz": "Kela olmayman", "ru": "Не смогу", "en": "Can't make it"},
    "rsvp_guests": {
        "uz": "Necha kishi bo'lasiz?",
        "ru": "Сколько вас будет?",
        "en": "How many of you?",
    },
    "rsvp_name": {
        "uz": "Ismingiz (ixtiyoriy)",
        "ru": "Ваше имя (необязательно)",
        "en": "Your name (optional)",
    },
    "rsvp_pick": {
        "uz": "Iltimos, javobni tanlang",
        "ru": "Пожалуйста, выберите ответ",
        "en": "Please choose an answer",
    },
    "rsvp_send": {"uz": "Yuborish", "ru": "Отправить", "en": "Send"},
    "rsvp_thanks_yes": {
        "uz": "Rahmat! Sizni kutamiz 🌸",
        "ru": "Спасибо! Ждём вас 🌸",
        "en": "Thank you! We look forward to seeing you 🌸",
    },
    "rsvp_thanks_no": {
        "uz": "Rahmat, javobingiz qabul qilindi",
        "ru": "Спасибо, ваш ответ получен",
        "en": "Thank you, we've got your answer",
    },
    "rsvp_failed": {
        "uz": "Yuborib bo'lmadi. Qaytadan urinib ko'ring.",
        "ru": "Не удалось отправить. Попробуйте ещё раз.",
        "en": "Couldn't send. Please try again.",
    },
    "rsvp_noscript": {
        "uz": "Javob berish uchun brauzerda skriptlar yoqilgan bo'lishi kerak.",
        "ru": "Чтобы ответить, включите в браузере JavaScript.",
        "en": "Please enable JavaScript to reply.",
    },
    "gone_title": {
        "uz": "Bu sahifa endi mavjud emas",
        "ru": "Этой страницы больше нет",
        "en": "This page is no longer available",
    },
    "gone_text": {
        "uz": "Havola eskirgan yoki muallif uni o'chirgan.",
        "ru": "Срок ссылки истёк, или автор её удалил.",
        "en": "The link has expired, or its author removed it.",
    },
    "og_yesno": {
        "uz": "💌 Senga maxsus savol",
        "ru": "💌 Для тебя особый вопрос",
        "en": "💌 A special question for you",
    },
    "og_yesno_desc": {"uz": "Ochib ko'r 😊", "ru": "Открой 😊", "en": "Open it 😊"},
    "og_invite_desc": {
        "uz": "Sizni taklif qilamiz",
        "ru": "Приглашаем вас",
        "en": "You are invited",
    },
}

#: What the Yo'q button says as it runs away. The first entry is its label;
#: every later one is shown ONCE, in order, a little warmer each time, and when
#: they run out the button leaves (static/js/page.js). Teasing, never pressure:
#: nothing here threatens, guilts or pushes -- tests/test_web_strings.py keeps
#: at least ten, all different, in every language.
NO_LINES: Final[dict[str, tuple[str, ...]]] = {
    "uz": (
        "Yo'q",
        "Yaxshilab o'ylab ko'r 🙂",
        "Aniqmi?",
        "Rostdanmi?",
        "Yana bir bor o'ylab ko'r...",
        "Balki baribir «Ha»? 😊",
        "Men shoshilmayman, kutaman ⏳",
        "Yuragimni sindirasanmi? 💔",
        "Bu tugma biroz uyatchan 🙈",
        "Ko'ryapsanmi, u qochyapti 🏃",
        "Oxirgi imkoniyat 😇",
        "Mayli, «Ha»ni bosaqol 💕",
        "«Yo'q» tugmasi ta'tilga chiqdi 🌴",
    ),
    "ru": (
        "Нет",
        "Подумай хорошенько 🙂",
        "Точно?",
        "Правда?",
        "Подумай ещё разок...",
        "Может, всё-таки «Да»? 😊",
        "Я не тороплю, подожду ⏳",
        "Разобьёшь мне сердце? 💔",
        "Эта кнопка немного стесняется 🙈",
        "Видишь, она убегает 🏃",
        "Последний шанс 😇",
        "Ладно, нажимай «Да» 💕",
        "Кнопка «Нет» ушла в отпуск 🌴",
    ),
    "en": (
        "No",
        "Think it over 🙂",
        "Are you sure?",
        "Really?",
        "Think once more...",
        "Maybe «Yes» after all? 😊",
        "No rush, I'll wait ⏳",
        "Will you break my heart? 💔",
        "This button is a little shy 🙈",
        "See? It's running away 🏃",
        "Last chance 😇",
        "Okay, just press «Yes» 💕",
        "The «No» button went on holiday 🌴",
    ),
}  # fmt: skip
NO_LINES["uz_cyrl"] = tuple(to_cyrillic(line) for line in NO_LINES["uz"])

#: The ready-made questions, picked from buttons in the bot. `custom` is the
#: customer's own words and has no entry here.
#:
#: Uzbek has no grammatical gender. Russian does, and "marry" and "valentine"
#: are written to a woman, the common case for a flower shop; anyone else
#: types their own question.
QUESTIONS: Final[dict[str, dict[str, str]]] = {
    "marry": {
        "uz": "Menga turmushga chiqasanmi?",
        "ru": "Выйдешь за меня замуж?",
        "en": "Will you marry me?",
    },
    "forgive": {
        "uz": "Meni kechirasanmi?",
        "ru": "Ты меня простишь?",
        "en": "Will you forgive me?",
    },
    "date": {
        "uz": "Men bilan uchrashuvga chiqasanmi?",
        "ru": "Пойдёшь со мной на свидание?",
        "en": "Will you go on a date with me?",
    },
    "valentine": {
        "uz": "Mening Valentinim bo'lasanmi?",
        "ru": "Будешь моей валентинкой?",
        "en": "Will you be my Valentine?",
    },
    "together": {
        "uz": "Sevgilim bo'lasanmi?",
        "ru": "Будешь со мной встречаться?",
        "en": "Will you be mine?",
    },
}

#: The line under "Hurraa!" once Ha is pressed.
CELEBRATIONS: Final[dict[str, dict[str, str]]] = {
    "marry": {
        "uz": "Bu hayotimdagi eng baxtli kun! 💍",
        "ru": "Это самый счастливый день в моей жизни! 💍",
        "en": "This is the happiest day of my life! 💍",
    },
    "forgive": {
        "uz": "Rahmat! Endi hammasi yaxshi bo'ladi 💐",
        "ru": "Спасибо! Теперь всё будет хорошо 💐",
        "en": "Thank you! Everything will be fine now 💐",
    },
    "date": {
        "uz": "Zo'r! Ko'rishguncha 💫",
        "ru": "Ура! До встречи 💫",
        "en": "Yay! See you soon 💫",
    },
    "valentine": {"uz": "Bilardim! 💘", "ru": "Я так и знал(а)! 💘", "en": "I knew it! 💘"},
    "together": {
        "uz": "Endi biz birgamiz 💞",
        "ru": "Теперь мы вместе 💞",
        "en": "Now we're together 💞",
    },
    "custom": {
        "uz": "Javobing uchun rahmat! 💖",
        "ru": "Спасибо за ответ! 💖",
        "en": "Thank you for your answer! 💖",
    },
}

#: Invitation event types, as stored in share_pages.event_type.
EVENT_LABELS: Final[dict[str, dict[str, str]]] = {
    "wedding": {"uz": "To'y", "ru": "Свадьба", "en": "Wedding"},
    "nikoh": {"uz": "Nikoh to'yi", "ru": "Никах", "en": "Nikah"},
    "fotiha": {"uz": "Fotiha to'yi", "ru": "Фатиха-туй", "en": "Engagement"},
    "birthday": {"uz": "Tug'ilgan kun", "ru": "День рождения", "en": "Birthday"},
    "beshik": {"uz": "Beshik to'yi", "ru": "Бешик-туй", "en": "Beshik toy"},
    "sunnat": {"uz": "Sunnat to'yi", "ru": "Суннат-туй", "en": "Sunnat toy"},
    "anniversary": {"uz": "Yubiley", "ru": "Юбилей", "en": "Anniversary"},
    "graduation": {"uz": "Bitiruv kechasi", "ru": "Выпускной", "en": "Graduation"},
    "corporate": {"uz": "Korporativ tadbir", "ru": "Корпоратив", "en": "Corporate event"},
    "other": {"uz": "Bayram", "ru": "Праздник", "en": "Celebration"},
}

#: What an invitation says when its author wrote no message of their own.
EVENT_MESSAGES: Final[dict[str, dict[str, str]]] = {
    "wedding": {
        "uz": "Aziz mehmonlar! Sizni hayotimizdagi eng quvonchli kun — to'y bazmimizga "
        "taklif etamiz.",
        "ru": "Дорогие гости! Приглашаем вас разделить с нами самый радостный день — нашу свадьбу.",
        "en": "Dear guests! We invite you to share the happiest day of our lives — our wedding.",
    },
    "nikoh": {
        "uz": "Sizni nikoh to'yimizga lutfan taklif etamiz.",
        "ru": "Приглашаем вас на наш никах.",
        "en": "We kindly invite you to our nikah ceremony.",
    },
    "fotiha": {
        "uz": "Sizni fotiha to'yimizga taklif etamiz. Quvonchimizga sherik bo'ling!",
        "ru": "Приглашаем вас на фатиха-туй. Разделите с нами радость!",
        "en": "We invite you to our engagement. Come and share our joy!",
    },
    "birthday": {
        "uz": "Tug'ilgan kun bazmiga taklif etamiz!",
        "ru": "Приглашаем на праздник в честь дня рождения!",
        "en": "You're invited to a birthday celebration!",
    },
    "beshik": {
        "uz": "Farzandimizning beshik to'yiga taklif etamiz.",
        "ru": "Приглашаем вас на бешик-туй нашего малыша.",
        "en": "We invite you to our little one's beshik toy.",
    },
    "sunnat": {
        "uz": "O'g'limizning sunnat to'yiga taklif etamiz.",
        "ru": "Приглашаем вас на суннат-туй нашего сына.",
        "en": "We invite you to our son's sunnat toy.",
    },
    "anniversary": {
        "uz": "Sizni yubiley tantanamizga taklif etamiz.",
        "ru": "Приглашаем вас на наш юбилей.",
        "en": "We invite you to our anniversary celebration.",
    },
    "graduation": {
        "uz": "Bitiruv kechamizga taklif etamiz!",
        "ru": "Приглашаем на наш выпускной вечер!",
        "en": "You're invited to our graduation party!",
    },
    "corporate": {
        "uz": "Sizni korporativ tadbirimizga taklif etamiz.",
        "ru": "Приглашаем вас на наше корпоративное мероприятие.",
        "en": "We invite you to our corporate event.",
    },
    "other": {
        "uz": "Sizni bayramimizga taklif etamiz!",
        "ru": "Приглашаем вас на наш праздник!",
        "en": "You're invited to our celebration!",
    },
}

_CLOSING_COUPLE = {
    "uz": "Sizni intizorlik bilan kutamiz!",
    "ru": "С нетерпением ждём вас!",
    "en": "We can't wait to celebrate with you!",
}
_CLOSING_FAMILY = {
    "uz": "Kelib, quvonchimizga sherik bo'ling!",
    "ru": "Приходите разделить нашу радость!",
    "en": "Come and share our joy!",
}
_CLOSING_PLAIN = {
    "uz": "Sizni kutib qolamiz!",
    "ru": "Будем рады вас видеть!",
    "en": "We look forward to seeing you!",
}
#: The invitation's last line, per event type (CP17). A preset like the
#: message: shown until the creator writes their own.
EVENT_CLOSINGS: Final[dict[str, dict[str, str]]] = {
    "wedding": _CLOSING_COUPLE,
    "nikoh": _CLOSING_COUPLE,
    "fotiha": _CLOSING_COUPLE,
    "birthday": _CLOSING_FAMILY,
    "beshik": _CLOSING_FAMILY,
    "sunnat": _CLOSING_FAMILY,
    "anniversary": _CLOSING_PLAIN,
    "graduation": _CLOSING_PLAIN,
    "other": _CLOSING_PLAIN,
    "corporate": {
        "uz": "Tashrifingizdan mamnun bo'lamiz.",
        "ru": "Будем рады вашему участию.",
        "en": "We would be glad to see you there.",
    },
}

#: Events with TWO names on the card -- a couple. Everything else names one
#: person, or one host.
COUPLE_EVENTS: Final = frozenset({"wedding", "nikoh", "fotiha"})


def _pick(table: dict[str, str], lang: str) -> str:
    if lang == "uz_cyrl":
        return table.get("uz_cyrl") or to_cyrillic(table["uz"])
    return table.get(lang) or table["uz"]


def text(key: str, lang: str) -> str:
    return _pick(_TEXT[key], lang)


def question(preset: str, lang: str) -> str:
    return _pick(QUESTIONS[preset], lang)


def celebration(preset: str, lang: str) -> str:
    return _pick(CELEBRATIONS.get(preset, CELEBRATIONS["custom"]), lang)


def event_label(event_type: str, lang: str) -> str:
    return _pick(EVENT_LABELS[event_type], lang)


def event_message(event_type: str, lang: str) -> str:
    return _pick(EVENT_MESSAGES[event_type], lang)


def event_closing(event_type: str, lang: str) -> str:
    return _pick(EVENT_CLOSINGS[event_type], lang)


def all_text(lang: str) -> dict[str, str]:
    """Every fixed string, for the template's `v.s`."""
    return {key: text(key, lang) for key in _TEXT}


def text_keys() -> tuple[str, ...]:
    return tuple(_TEXT)
