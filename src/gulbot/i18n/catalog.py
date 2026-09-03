"""User-facing strings, uz + ru.

Every key must exist in every language; tests/test_i18n.py fails the build
otherwise. Keys whose value is a button LABEL are listed in BUTTON_KEYS, because
the handler-shadowing sweep probes the dispatcher with each of them.
"""

from __future__ import annotations

from typing import Final

LANGUAGES: Final = ("uz", "ru")
DEFAULT_LANGUAGE: Final = "uz"

CATALOG: Final[dict[str, dict[str, str]]] = {
    "start.choose_language": {
        "uz": "Assalomu alaykum! Tilni tanlang:",
        "ru": "Здравствуйте! Выберите язык:",
    },
    "start.welcome_back": {
        "uz": "Xush kelibsiz, {name}!",
        "ru": "С возвращением, {name}!",
    },
    "language.saved": {
        "uz": "Til o'zbekchaga o'zgartirildi.",
        "ru": "Язык изменён на русский.",
    },
    "menu.title": {
        "uz": "Asosiy menyu. Nima qilamiz?",
        "ru": "Главное меню. Что делаем?",
    },
    "settings.title": {
        "uz": "Sozlamalar",
        "ru": "Настройки",
    },
    "help.text": {
        "uz": (
            "Gulbot muhim sanalaringizni eslatib turadi va gul buyurtma "
            "berishga yordam beradi.\n\nSavollar bo'lsa, operatorga yozing."
        ),
        "ru": (
            "Gulbot напоминает о ваших важных датах и помогает заказать "
            "цветы.\n\nЕсли есть вопросы, напишите оператору."
        ),
    },
    "nav.cancelled": {
        "uz": "Bekor qilindi.",
        "ru": "Отменено.",
    },
    "nav.nothing_to_cancel": {
        "uz": "Bekor qiladigan narsa yo'q.",
        "ru": "Нечего отменять.",
    },
    "common.unknown": {
        "uz": "Tushunmadim. Quyidagi tugmalardan foydalaning.",
        "ru": "Не понял. Воспользуйтесь кнопками ниже.",
    },
    # --- occasions -------------------------------------------------------
    "occasions.empty": {
        "uz": "Sizda hali saqlangan sana yo'q.",
        "ru": "У вас пока нет сохранённых дат.",
    },
    "occasions.list_title": {
        "uz": "Sizning sanalaringiz:",
        "ru": "Ваши даты:",
    },
    "occasions.choose_type": {
        "uz": "Bu sana kim uchun?",
        "ru": "Для кого эта дата?",
    },
    "occasions.enter_label": {
        "uz": "Nomini yozing (masalan: Singlim). 64 belgigacha.",
        "ru": "Напишите название (например: Сестра). До 64 символов.",
    },
    "occasions.label_empty": {
        "uz": "Nom bo'sh bo'lmasligi kerak. Qaytadan yozing.",
        "ru": "Название не может быть пустым. Напишите ещё раз.",
    },
    "occasions.label_trimmed": {
        "uz": "Nom 64 belgigacha qisqartirildi.",
        "ru": "Название сокращено до 64 символов.",
    },
    "occasions.choose_month": {
        "uz": "Oyni tanlang:",
        "ru": "Выберите месяц:",
    },
    "occasions.choose_day": {
        "uz": "Kunni tanlang:",
        "ru": "Выберите день:",
    },
    "occasions.enter_year": {
        "uz": "Yilni yozing (masalan: 1990) yoki o'tkazib yuboring.",
        "ru": "Напишите год (например: 1990) или пропустите.",
    },
    "occasions.year_invalid": {
        "uz": "Yil 1900 va 2100 orasida, 4 raqamli bo'lishi kerak.",
        "ru": "Год должен быть четырёхзначным, между 1900 и 2100.",
    },
    "occasions.year_not_leap": {
        "uz": "29-fevral faqat kabisa yilida bo'ladi. Boshqa yil yozing yoki o'tkazib yuboring.",
        "ru": "29 февраля бывает только в високосный год. Укажите другой год или пропустите.",
    },
    # Restates every field before anything is written. Nothing is saved until
    # the customer taps Ha.
    "occasions.confirm": {
        "uz": "Kim: {label}\nTuri: {type_name}\nSana: {date}\n\nSaqlaymizmi?",
        "ru": "Кто: {label}\nТип: {type_name}\nДата: {date}\n\nСохраняем?",
    },
    "occasions.saved": {
        "uz": "Saqlandi: {label} — {date}",
        "ru": "Сохранено: {label} — {date}",
    },
    "occasions.duplicate": {
        "uz": "Bu sana allaqachon saqlangan.",
        "ru": "Эта дата уже сохранена.",
    },
    "occasions.deactivated": {
        "uz": "O'chirildi: {label}",
        "ru": "Удалено: {label}",
    },
    "occasions.not_found": {
        "uz": "Bu sana topilmadi.",
        "ru": "Эта дата не найдена.",
    },
    "occasions.consent": {
        "uz": (
            "Saqlash orqali siz shu sanani eslatma yuborish uchun saqlashimizga rozilik bildirasiz."
        ),
        "ru": ("Сохраняя, вы соглашаетесь на хранение этой даты для отправки напоминаний."),
    },
    # --- recipients & chaining -------------------------------------------
    "recipients.empty": {
        "uz": "Sizda hali saqlangan odam yo'q.",
        "ru": "У вас пока нет сохранённых людей.",
    },
    "recipients.list_title": {
        "uz": "Sizning odamlaringiz:",
        "ru": "Ваши люди:",
    },
    "recipients.detail": {
        "uz": "{label}\n\nSanalari:\n{dates}",
        "ru": "{label}\n\nДаты:\n{dates}",
    },
    "recipients.no_dates": {
        "uz": "Hali sana yo'q.",
        "ru": "Пока нет дат.",
    },
    "recipients.ask_more_dates": {
        "uz": "{label} uchun yana muhim sana bormi?",
        "ru": "Есть ещё важные даты для {label}?",
    },
    "recipients.ask_more_people": {
        "uz": "Yana odam qo'shamizmi?",
        "ru": "Добавим ещё человека?",
    },
    "recipients.onboarding_done": {
        "uz": "Ajoyib! Hammasi saqlandi. Vaqti kelganda eslatamiz.",
        "ru": "Отлично! Всё сохранено. Напомним, когда придёт время.",
    },
    "recipients.renamed": {
        "uz": "Nomi o'zgartirildi: {label}",
        "ru": "Имя изменено: {label}",
    },
    "recipients.deactivated": {
        "uz": "O'chirildi: {label}",
        "ru": "Удалено: {label}",
    },
    "recipients.not_found": {
        "uz": "Bu odam topilmadi.",
        "ru": "Этот человек не найден.",
    },
    "recipients.choose_new_label": {
        "uz": "Yangi nomni tanlang yoki yozing:",
        "ru": "Выберите новое имя или напишите своё:",
    },
    "occasions.date_updated": {
        "uz": "Sana yangilandi: {date}",
        "ru": "Дата обновлена: {date}",
    },
    # --- preferences ------------------------------------------------------
    "prefs.ask_flower": {
        "uz": "{label} qanday gullarni yoqtiradi?",
        "ru": "Какие цветы любит {label}?",
    },
    "prefs.ask_reminder_count": {
        "uz": "Necha marta oldindan eslataylik?",
        "ru": "Сколько раз напомнить заранее?",
    },
    "prefs.ask_send_time": {
        "uz": "Qaysi vaqtda eslataylik?",
        "ru": "В какое время напоминать?",
    },
    "prefs.saved": {
        "uz": "Sozlamalar saqlandi.",
        "ru": "Настройки сохранены.",
    },
    "flower.atirgul": {"uz": "Atirgul", "ru": "Розы"},
    "flower.tyulpan": {"uz": "Tyulpan", "ru": "Тюльпаны"},
    "flower.lola": {"uz": "Lola", "ru": "Лола"},
    "ibtn.flower_other": {"uz": "Boshqa", "ru": "Другое"},
    "ibtn.count_1": {"uz": "1 marta", "ru": "1 раз"},
    "ibtn.count_2": {"uz": "2 marta", "ru": "2 раза"},
    "ibtn.count_3": {"uz": "3 marta", "ru": "3 раза"},
    "ibtn.time_morning": {"uz": "Ertalab (09:00)", "ru": "Утром (09:00)"},
    "ibtn.time_noon": {"uz": "Tushlikda (13:00)", "ru": "Днём (13:00)"},
    "ibtn.time_evening": {"uz": "Kechqurun (20:00)", "ru": "Вечером (20:00)"},
    "ibtn.skip": {"uz": "O'tkazib yuborish", "ru": "Пропустить"},
    # --- occasion type presets ------------------------------------------
    "occtype.wife": {"uz": "Xotinim", "ru": "Жена"},
    "occtype.spouse": {"uz": "Turmush o'rtog'im", "ru": "Супруг(а)"},
    "occtype.mother": {"uz": "Onam", "ru": "Мама"},
    "occtype.father": {"uz": "Otam", "ru": "Папа"},
    "occtype.child": {"uz": "Farzandim", "ru": "Мой ребёнок"},
    "occtype.friend": {"uz": "Do'stim", "ru": "Друг"},
    "occtype.custom": {"uz": "Boshqa", "ru": "Другое"},
    # --- months ----------------------------------------------------------
    "month.1": {"uz": "Yanvar", "ru": "Январь"},
    "month.2": {"uz": "Fevral", "ru": "Февраль"},
    "month.3": {"uz": "Mart", "ru": "Март"},
    "month.4": {"uz": "Aprel", "ru": "Апрель"},
    "month.5": {"uz": "May", "ru": "Май"},
    "month.6": {"uz": "Iyun", "ru": "Июнь"},
    "month.7": {"uz": "Iyul", "ru": "Июль"},
    "month.8": {"uz": "Avgust", "ru": "Август"},
    "month.9": {"uz": "Sentabr", "ru": "Сентябрь"},
    "month.10": {"uz": "Oktabr", "ru": "Октябрь"},
    "month.11": {"uz": "Noyabr", "ru": "Ноябрь"},
    "month.12": {"uz": "Dekabr", "ru": "Декабрь"},
    # --- inline buttons ---------------------------------------------------
    "ibtn.add_occasion": {"uz": "➕ Sana qo'shish", "ru": "➕ Добавить дату"},
    "ibtn.skip_year": {"uz": "O'tkazib yuborish", "ru": "Пропустить"},
    "ibtn.save": {"uz": "✅ Saqlash", "ru": "✅ Сохранить"},
    "ibtn.discard": {"uz": "✖️ Bekor qilish", "ru": "✖️ Отмена"},
    "ibtn.back": {"uz": "⬅️ Orqaga", "ru": "⬅️ Назад"},
    "ibtn.yes": {"uz": "Ha", "ru": "Да"},
    "ibtn.no": {"uz": "Yo'q", "ru": "Нет"},
    "ibtn.rename": {"uz": "✏️ Nomini o'zgartirish", "ru": "✏️ Изменить имя"},
    "ibtn.add_date": {"uz": "➕ Sana qo'shish", "ru": "➕ Добавить дату"},
    "ibtn.add_person": {"uz": "➕ Odam qo'shish", "ru": "➕ Добавить человека"},
    "ibtn.custom_label": {"uz": "✍️ O'zim yozaman", "ru": "✍️ Напишу сам"},
    "ibtn.deactivate": {"uz": "🗑 O'chirish", "ru": "🗑 Удалить"},
    # --- button labels ---------------------------------------------------
    "btn.language.uz": {"uz": "🇺🇿 O'zbekcha", "ru": "🇺🇿 O'zbekcha"},
    "btn.language.ru": {"uz": "🇷🇺 Русский", "ru": "🇷🇺 Русский"},
    "btn.menu.settings": {"uz": "⚙️ Sozlamalar", "ru": "⚙️ Настройки"},
    "btn.menu.help": {"uz": "ℹ️ Yordam", "ru": "ℹ️ Помощь"},
    "btn.settings.change_language": {
        "uz": "🌐 Tilni o'zgartirish",
        "ru": "🌐 Сменить язык",
    },
    "btn.nav.back": {"uz": "⬅️ Orqaga", "ru": "⬅️ Назад"},
    "btn.nav.cancel": {"uz": "✖️ Bekor qilish", "ru": "✖️ Отмена"},
    "btn.menu.occasions": {"uz": "📅 Sanalarim", "ru": "📅 Мои даты"},
}

BUTTON_KEYS: Final = tuple(k for k in CATALOG if k.startswith("btn."))
