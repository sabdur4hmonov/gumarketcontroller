"""The public pages' own words, in four languages.

Uzbek Cyrillic is generated from the Latin by `to_cyrillic`, so the
transliteration is pinned against words checked by hand -- including the
places where a naive letter-for-letter mapping goes wrong (o', g', the
word-initial e, the tutuq belgisi, yo' that is not ё).
"""

from __future__ import annotations

import re

import pytest

from gulbot.models.share_page import EVENT_TYPES, PAGE_LANGUAGES, QUESTION_PRESETS
from gulbot.web import strings


@pytest.mark.parametrize(
    ("latin", "cyrillic"),
    [
        ("Ha", "Ҳа"),
        ("Yo'q", "Йўқ"),
        ("to'y", "тўй"),
        ("Tug'ilgan kun", "Туғилган кун"),
        ("O'g'limizning", "Ўғлимизнинг"),
        ("Gul buyurtma qilish", "Гул буюртма қилиш"),
        ("Ismingiz (ixtiyoriy)", "Исмингиз (ихтиёрий)"),
        ("Bu sahifa endi mavjud emas", "Бу саҳифа энди мавжуд эмас"),
        ("Yubiley", "Юбилей"),
        ("yaxshi", "яхши"),
        ("ma'lumot", "маълумот"),
        ("Shanba", "Шанба"),
        ("Chorshanba", "Чоршанба"),
        ("Kelaman", "Келаман"),
        ("Faqat «Ha» qoldi 💕", "Фақат «Ҳа» қолди 💕"),
        ("Toshkent, «Navro‘z»", "Тошкент, «Наврўз»"),
    ],
)
def test_to_cyrillic(latin: str, cyrillic: str) -> None:
    assert strings.to_cyrillic(latin) == cyrillic


def test_placeholders_survive_transliteration() -> None:
    """str.format fills these in later; a transliterated name would not match."""
    assert strings.to_cyrillic("Sahifa «{shop}» gul do'koni") == "Саҳифа «{shop}» гул дўкони"
    assert strings.text("made_with", "uz_cyrl").format(shop="Lola") == (
        "Саҳифа «Lola» гул дўкони боти орқали яратилган"
    )


def test_every_fixed_string_exists_in_every_language() -> None:
    for lang in PAGE_LANGUAGES:
        texts = strings.all_text(lang)
        assert set(texts) == set(strings.text_keys())
        assert all(value.strip() for value in texts.values()), lang


def test_the_cyrillic_page_has_no_latin_words_left() -> None:
    """A word missed by the transliteration would show up as Latin letters."""
    for key, value in strings.all_text("uz_cyrl").items():
        value = re.sub(r"\{[a-z_]+\}", "", value)
        latin_letters = [ch for ch in value if "a" <= ch.lower() <= "z"]
        assert not latin_letters, f"{key}: {value!r}"


def test_every_question_and_event_has_text_in_every_language() -> None:
    for lang in PAGE_LANGUAGES:
        for preset in QUESTION_PRESETS:
            if preset != "custom":
                assert strings.question(preset, lang)
            assert strings.celebration(preset, lang)
        for event in EVENT_TYPES:
            assert strings.event_label(event, lang)
            assert strings.event_message(event, lang)


def test_the_no_button_has_somewhere_to_go_in_every_language() -> None:
    for lang in PAGE_LANGUAGES:
        lines = strings.NO_LINES[lang]
        assert lines[0] == strings.text("no", lang)
        assert len(lines) >= 5


def test_calendar_words_cover_the_year_and_the_week() -> None:
    for lang in PAGE_LANGUAGES:
        assert len(strings.MONTHS[lang]) == 12
        assert len(strings.WEEKDAYS[lang]) == 7
