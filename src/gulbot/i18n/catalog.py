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
        "uz": "🌸 Assalomu alaykum! Gulbotga xush kelibsiz.\nQaysi tilda gaplashamiz?",
        "ru": "Здравствуйте! Выберите язык:",
    },
    "start.welcome_back": {
        "uz": "Xush kelibsiz, {name}!",
        "ru": "С возвращением, {name}!",
    },
    "language.saved": {
        "uz": "Zo'r, o'zbekchada davom etamiz.",
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
        "uz": "Bekor qildik.",
        "ru": "Отменено.",
    },
    "nav.nothing_to_cancel": {
        "uz": "Bekor qiladigan narsa yo'q.",
        "ru": "Нечего отменять.",
    },
    "common.unknown": {
        "uz": "Quyidagi tugmalardan birini tanlang 🙂",
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
        "uz": "Kimning muhim sanasini eslatib turaylik?",
        "ru": "Для кого эта дата?",
    },
    "occasions.enter_label": {
        "uz": 'Ismini yoki qarindoshligini yozing — masalan, "Singlim Aziza".',
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
        "uz": "Qaysi oyda?",
        "ru": "Выберите месяц:",
    },
    "occasions.choose_day": {
        "uz": "Qaysi kuni?",
        "ru": "Выберите день:",
    },
    "occasions.enter_year": {
        "uz": "Yilini bilsangiz yozing (masalan, 1990). Bilmasangiz — o'tkazib yuboring.",
        "ru": "Напишите год (например: 1990) или пропустите.",
    },
    "occasions.year_invalid": {
        "uz": "Yilni 4 raqam bilan yozing, masalan 1990.",
        "ru": "Год должен быть четырёхзначным, между 1900 и 2100.",
    },
    "occasions.year_not_leap": {
        "uz": "29-fevral faqat kabisa yilida bo'ladi. Boshqa yilni yozing yoki o'tkazib yuboring.",
        "ru": "29 февраля бывает только в високосный год. Укажите другой год или пропустите.",
    },
    # Restates every field before anything is written. Nothing is saved until
    # the customer taps Ha.
    "occasions.confirm": {
        "uz": "📅 {label} — {type_name}\n{date}\n\nShu sanani eslatib turaymizmi?",
        "ru": "Кто: {label}\nТип: {type_name}\nДата: {date}\n\nСохраняем?",
    },
    "occasions.saved": {
        "uz": "✅ Saqladik! {label} — {date}. Vaqti kelganda eslatamiz.",
        "ru": "Сохранено: {label} — {date}",
    },
    "occasions.duplicate": {
        "uz": "Bu sana allaqachon ro'yxatda bor.",
        "ru": "Эта дата уже сохранена.",
    },
    "occasions.deactivated": {
        "uz": "{label} ro'yxatdan olib tashlandi.",
        "ru": "Удалено: {label}",
    },
    "occasions.not_found": {
        "uz": "Bu sana topilmadi.",
        "ru": "Эта дата не найдена.",
    },
    "occasions.consent": {
        "uz": "Saqlasak, bu sanani faqat sizga eslatma yuborish uchun saqlaymiz.",
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
        "uz": "{label} uchun boshqa muhim sana ham bormi?",
        "ru": "Есть ещё важные даты для {label}?",
    },
    "recipients.ask_more_people": {
        "uz": "Yana kimnidir qo'shamizmi?",
        "ru": "Добавим ещё человека?",
    },
    "recipients.onboarding_done": {
        "uz": "🌸 Hammasi tayyor! Muhim kunlar yaqinlashganda sizga eslatamiz.",
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
        "uz": "{label} qanday gullarni yoqtiradi? 🌷",
        "ru": "Какие цветы любит {label}?",
    },
    "prefs.ask_reminder_count": {
        "uz": "Sanadan oldin necha marta eslataylik?",
        "ru": "Сколько раз напомнить заранее?",
    },
    "prefs.ask_send_time": {
        "uz": "Kun davomida qaysi vaqtda eslatganimiz qulay?",
        "ru": "В какое время напоминать?",
    },
    "prefs.saved": {
        "uz": "Eslatma sozlamalari saqlandi.",
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
    # Presets are STORED first person ("Onam" = my mother) because that is how
    # the customer picks them. The bot must not speak that way about them, so
    # every sentence addressed to the customer uses these second-person forms
    # instead. Custom labels are never converted -- see utils.render.
    "recipient.addr.mother": {"uz": "Onangiz", "ru": "Ваша мама"},
    "recipient.addr.spouse": {"uz": "Turmush o‘rtog‘ingiz", "ru": "Ваш(а) супруг(а)"},
    "recipient.addr.older_sister": {"uz": "Opangiz", "ru": "Ваша старшая сестра"},
    "recipient.addr.younger_sister": {"uz": "Singlingiz", "ru": "Ваша младшая сестра"},
    "recipient.addr.paternal_aunt": {"uz": "Ammangiz", "ru": "Ваша тётя"},
    "recipient.addr.maternal_aunt": {"uz": "Xolangiz", "ru": "Ваша тётя"},
    # --- reminders --------------------------------------------------------
    "reminder.heading": {
        "uz": "🌸 Eslatma!",
        "ru": "🌸 Напоминание!",
    },
    "reminder.single": {
        "uz": "{when} {label}ning {kind} — {date}.",
        "ru": "{when}: {label} — {kind}, {date}.",
    },
    # A CUSTOM label cannot take the -ning genitive above without the bot
    # appearing to claim the relation, so the sentence is reshaped into the same
    # appositive form the merged list already uses. No possessive suffix, and it
    # is grammatical for any free text.
    "reminder.single_custom": {
        "uz": "{when} — {label}, {kind}, {date}.",
        "ru": "{when}: {label} — {kind}, {date}.",
    },
    "reminder.merged_intro": {
        "uz": "Yaqin kunlarda:",
        "ru": "В ближайшие дни:",
    },
    "reminder.item": {
        "uz": "• {label} — {kind}, {date} ({when})",
        "ru": "• {label} — {kind}, {date} ({when})",
    },
    # Capitalised variants, for when the phrase OPENS a sentence. Separate keys
    # rather than .capitalize(): a numeric "3 kundan keyin" would be untouched
    # by it, so the two cases only look the same by accident.
    "reminder.whencap.today": {"uz": "Bugun", "ru": "Сегодня"},
    "reminder.whencap.tomorrow": {"uz": "Ertaga", "ru": "Завтра"},
    "reminder.whencap.in_days": {"uz": "{days} kundan keyin", "ru": "Через {days} дн."},
    # The kind as it reads INSIDE a sentence, which is not the button label.
    "occkind.poss.birthday": {"uz": "tug'ilgan kuni", "ru": "день рождения"},
    "occkind.poss.anniversary": {"uz": "nikoh to'yi", "ru": "годовщина свадьбы"},
    "occkind.poss.other": {"uz": "muhim sanasi", "ru": "важная дата"},
    "reminder.when.today": {"uz": "bugun", "ru": "сегодня"},
    "reminder.when.tomorrow": {"uz": "ertaga", "ru": "завтра"},
    "reminder.when.in_days": {"uz": "{days} kundan keyin", "ru": "через {days} дн."},
    # --- CP10: ordering ---------------------------------------------------
    "ibtn.order_now": {"uz": "💐 Buyurtma berish", "ru": "💐 Заказать"},
    "order.choose_date": {
        "uz": "📅 Qachon yetkazib beraylik?",
        "ru": "📅 Когда доставить?",
    },
    "order.no_slots": {
        "uz": "Kechirasiz, hozircha bo‘sh vaqt yo‘q. Keyinroq urinib ko‘ring.",
        "ru": "Извините, свободного времени пока нет. Попробуйте позже.",
    },
    "order.choose_hour": {"uz": "🕐 Soat nechchida?", "ru": "🕐 В котором часу?"},
    # Names BOTH ways rather than asking "how", so the location option is
    # visible in the question and not only in a button. The shop owner
    # missed the pin entirely on a first pass through their own bot.
    "order.choose_location": {
        "uz": "📍 Qayerga yetkazib beraylik?\n\n"
        "Joylashuvingizni yuboring — shunda kuryer aniq topadi. "
        "Yoki manzilni o‘zingiz yozing.",
        "ru": "📍 Куда доставить?\n\n"
        "Отправьте локацию — курьеру будет точнее. "
        "Или напишите адрес сами.",
    },
    "ibtn.location_text": {"uz": "✍️ Manzil yozish", "ru": "✍️ Написать адрес"},
    # The pin goes FIRST in the keyboard and says what it is for, not what
    # it is called.
    "ibtn.location_pin": {
        "uz": "📍 Joylashuvni yuborish (tezroq)",
        "ru": "📍 Отправить локацию (быстрее)",
    },
    "order.enter_address": {"uz": "Manzilni yozing:", "ru": "Напишите адрес:"},
    "order.address_empty": {
        "uz": "Manzil bo‘sh bo‘lmasligi kerak. Qaytadan yozing.",
        "ru": "Адрес не может быть пустым. Напишите ещё раз.",
    },
    "order.share_location": {
        "uz": "Pastdagi tugma orqali joylashuvingizni yuboring.",
        "ru": "Отправьте локацию кнопкой ниже.",
    },
    "btn.share_location": {
        "uz": "📍 Joylashuvni yuborish",
        "ru": "📍 Отправить локацию",
    },
    "order.enter_landmark": {
        "uz": "🧭 Mo‘ljalni yozing (masalan: ko‘k eshik, dorixona yonida):",
        "ru": "🧭 Напишите ориентир (например: синяя дверь, рядом с аптекой):",
    },
    "order.landmark_empty": {
        "uz": "Mo‘ljal bo‘sh bo‘lmasligi kerak. Qaytadan yozing.",
        "ru": "Ориентир не может быть пустым. Напишите ещё раз.",
    },
    # {bouquet} is REUSED from the reminder keys below, so the
    # "narx operator tomonidan tasdiqlanadi" wording lives in exactly one place.
    "order.summary": {
        "uz": "{bouquet}\n\n📅 {date}, soat {hour}\n📍 {location}\n🧭 {landmark}\n👤 {recipient}",
        "ru": "{bouquet}\n\n📅 {date}, {hour}\n📍 {location}\n🧭 {landmark}\n👤 {recipient}",
    },
    "order.confirm": {
        "uz": "Buyurtmani tasdiqlaymizmi?\n\n{summary}",
        "ru": "Подтверждаем заказ?\n\n{summary}",
    },
    "order.location_pin": {"uz": "Joylashuv yuborilgan", "ru": "Локация отправлена"},
    "order.placed": {
        "uz": "✅ Buyurtmangiz qabul qilindi!\n\n{summary}\n\nTez orada bog‘lanamiz.",
        "ru": "✅ Заказ принят!\n\n{summary}\n\nСкоро свяжемся с вами.",
    },
    "order.gone": {
        "uz": "Bu buyurtmani davom ettirib bo‘lmadi. Qaytadan boshlang.",
        "ru": "Не удалось продолжить заказ. Начните заново.",
    },
    # CP9. The bouquet line, appended under the reminder as the photo caption.
    "reminder.bouquet": {
        "uz": "💐 <b>{name}</b> — {price} so‘m",
        "ru": "💐 <b>{name}</b> — {price} сум",
    },
    # An unpriced post is SHOWN, never hidden. A named requirement since the
    # original design brief.
    "reminder.bouquet.no_price": {
        "uz": "💐 <b>{name}</b> — narx operator tomonidan tasdiqlanadi",
        "ru": "💐 <b>{name}</b> — цену подтвердит оператор",
    },
    "reminder.footer": {
        "uz": "Gul bilan xursand qilamizmi? /start",
        "ru": "Хотите заказать цветы? /start",
    },
    # --- occasion type presets ------------------------------------------
    # Button order follows RecipientType's declaration order.
    "occtype.mother": {"uz": "Onam", "ru": "Мама"},
    "occtype.spouse": {"uz": "Turmush o'rtog'im", "ru": "Супруг(а)"},
    "occtype.older_sister": {"uz": "Opa", "ru": "Старшая сестра"},
    "occtype.younger_sister": {"uz": "Singil", "ru": "Младшая сестра"},
    "occtype.paternal_aunt": {"uz": "Amma", "ru": "Тётя (по отцу)"},
    "occtype.maternal_aunt": {"uz": "Xola", "ru": "Тётя (по матери)"},
    "occtype.custom": {"uz": "Boshqa", "ru": "Другое"},
    # --- what kind of date it is -----------------------------------------
    "occkind.birthday": {"uz": "Tug'ilgan kun", "ru": "День рождения"},
    "occkind.anniversary": {"uz": "Nikoh to'yi", "ru": "Годовщина свадьбы"},
    "occkind.other": {"uz": "Boshqa muhim sana", "ru": "Другая важная дата"},
    "occasions.choose_kind": {
        "uz": "Bu qanday sana?",
        "ru": "Что это за дата?",
    },
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
    # --- CP10b. What the SHOP sees in its own group ----------------------
    # Not customer copy. The shop's operating language is Uzbek; `ru` exists
    # because the parity test requires every key in both, not because a
    # Russian-speaking shop exists yet. When one does, this is where it lives.
    "group.new_order": {
        "uz": "🆕 <b>Yangi buyurtma #{id}</b>",
        "ru": "🆕 <b>Новый заказ #{id}</b>",
    },
    # {hours} is read from the ping's own offset, never recomputed from the
    # clock: the shop is told the interval that was SCHEDULED, so a tick that
    # runs late does not silently rewrite the number.
    "group.ping": {
        "uz": "⏰ <b>#{id} — yetkazishgacha {hours} soat</b>",
        "ru": "⏰ <b>#{id} — до доставки {hours} ч</b>",
    },
    "group.card": {
        "uz": "{heading}\n\n{bouquet}\n\n📅 {date}, soat {hour}\n"
        "📍 {location}\n🧭 {landmark}\n"
        "🎁 {recipient}\n👤 {customer}",
        "ru": "{heading}\n\n{bouquet}\n\n📅 {date}, {hour}\n"
        "📍 {location}\n🧭 {landmark}\n"
        "🎁 {recipient}\n👤 {customer}",
    },
    "group.pin": {
        "uz": '{lat}, {lon} — <a href="{url}">xaritada ochish</a>',
        "ru": '{lat}, {lon} — <a href="{url}">открыть на карте</a>',
    },
    # An unverified number is SHOWN and marked, never withheld: the courier
    # still needs something to dial. See customers.phone_verified.
    "group.phone_unverified": {
        "uz": "{phone} (tasdiqlanmagan)",
        "ru": "{phone} (не подтверждён)",
    },
    # Orders placed before CP12 have no answer. An honest blank beats an
    # invented name a courier might read out at a door.
    "group.no_recipient": {
        "uz": "kimga topshirilishi ko‘rsatilmagan",
        "ru": "получатель не указан",
    },
    "group.no_phone": {
        "uz": "telefon raqami yo‘q",
        "ru": "номер не указан",
    },
    "group.customer": {
        "uz": '{phone} · <a href="tg://user?id={tg}">mijoz</a>',
        "ru": '{phone} · <a href="tg://user?id={tg}">клиент</a>',
    },
    # --- CP10c. The customer's phone number ------------------------------
    # Asked at the END of onboarding, where the customer has already got value
    # from the bot, rather than at the start where it is pure friction. Skippable
    # there and required at order time, because that is the moment it is needed
    # and the moment the reason is obvious.
    "phone.ask_onboarding": {
        "uz": (
            "Buyurtma bergangingizda kuryer siz bilan bog‘lanishi uchun "
            "telefon raqamingiz kerak bo‘ladi.\n\n"
            "Pastdagi tugma orqali yuboring yoki keyinroq aytasiz."
        ),
        "ru": (
            "Когда вы сделаете "
            "заказ, курьеру "
            "понадобится "
            "ваш номер.\n\n"
            "Отправьте кнопкой "
            "ниже или позже."
        ),
    },
    # At order time the reason is concrete, so it is stated concretely.
    "phone.ask_order": {
        "uz": ("Kuryer yetkazib berishdan oldin bog‘lanishi uchun telefon raqamingizni yuboring."),
        "ru": ("Отправьте номер телефона — курьер позвонит перед доставкой."),
    },
    "phone.saved": {
        "uz": "Raqamingiz saqlandi: {phone}",
        "ru": "Номер сохранён: {phone}",
    },
    "phone.invalid": {
        "uz": (
            "Bu raqamga o‘xshamadi. Masalan: 90 123 45 67 — yoki pastdagi tugmadan foydalaning."
        ),
        "ru": ("Не похоже на номер. Например: 90 123 45 67 — или нажмите кнопку ниже."),
    },
    # Someone else's contact is not this customer's number. Storing it would put
    # a stranger's number on the shop's card under this customer's name.
    "phone.not_yours": {
        "uz": ("Bu boshqa odamning raqami. O‘z raqamingizni tugma orqali yuboring yoki yozing."),
        "ru": ("Это чужой номер. Отправьте свой кнопкой или напишите."),
    },
    # --- CP11.5. Health, for the SHOP's group. Not customer copy.
    # The summary is deliberately dull: it is read at a glance every day,
    # and its ABSENCE is the thing that means something.
    "health.summary": {
        "uz": "📊 <b>Bugun:</b> {reminders} eslatma, {orders} buyurtma.",
        "ru": "📊 <b>Сегодня:</b> {reminders} напоминаний, {orders} заказов.",
    },
    # Appended to the summary only when something is parked, so a clean day
    # stays one short line.
    "health.summary.parked": {
        "uz": "\n⚠️ {count} ta xabar yuborilmadi va to‘xtatildi.",
        "ru": "\n⚠️ {count} сообщений не отправлено.",
    },
    # The alarm. Says WHAT is stuck and HOW LONG, because "something is
    # wrong" is not actionable.
    "health.stalled": {
        "uz": "🚨 <b>Diqqat:</b> {count} ta xabar {minutes} daqiqadan beri yuborilmayapti."
        "\nBot ishlayotganini tekshiring.",
        "ru": "🚨 <b>Внимание:</b> {count} сообщений не отправлено уже {minutes} минут."
        "\nПроверьте работу бота.",
    },
    "health.parked": {
        "uz": "🚨 <b>Diqqat:</b> {count} ta xabar bir necha marta yuborilmadi va to‘xtatildi.",
        "ru": "🚨 <b>Внимание:</b> {count} сообщений отклонено после нескольких попыток.",
    },
    # --- CP11. Browsing the catalogue without a reminder to start from ----
    "browse.title": {
        "uz": "💐 Qaysi guldastani ko‘rmoqchisiz?",
        "ru": "💐 Какой букет посмотрим?",
    },
    "browse.empty": {
        "uz": "Hozircha guldastalar yo‘q. Tez orada qo‘shamiz!",
        "ru": "Пока нет букетов. Скоро добавим!",
    },
    "browse.gone": {
        "uz": "Bu guldasta endi mavjud emas.",
        "ru": "Этого букета больше нет.",
    },
    # The list row. Price on the same line, because a customer scanning a list
    # is choosing on price as much as on name.
    "browse.row": {"uz": "{name} — {price}", "ru": "{name} — {price}"},
    "browse.row.no_price": {"uz": "{name}", "ru": "{name}"},
    # --- CP12. Who takes delivery -----------------------------------------
    # NOT the same question as "whose birthday is it". The person placing the
    # order is often not the person the courier hands the flowers to.
    "order.ask_recipient": {
        "uz": "👤 Kimga topshiriladi?\n\nQabul qiluvchining ismini yozing.",
        "ru": "👤 Кому вручить?\n\nНапишите имя получателя.",
    },
    # When the order came from a reminder the bot already knows the name, so it
    # is offered as a button and typing is the fallback rather than the default.
    "order.ask_recipient_known": {
        "uz": "👤 Kimga topshiriladi?",
        "ru": "👤 Кому вручить?",
    },
    "order.recipient_empty": {
        "uz": "Ism bo‘sh bo‘lmasligi kerak. Qaytadan yozing.",
        "ru": "Имя не может быть пустым. Напишите ещё раз.",
    },
    # --- button labels ---------------------------------------------------
    "btn.language.uz": {"uz": "🇺🇿 O'zbekcha", "ru": "🇺🇿 O'zbekcha"},
    "btn.language.ru": {"uz": "🇷🇺 Русский", "ru": "🇷🇺 Русский"},
    "btn.menu.settings": {"uz": "⚙️ Sozlamalar", "ru": "⚙️ Настройки"},
    "btn.menu.help": {"uz": "ℹ️ Yordam", "ru": "ℹ️ Помощь"},
    "btn.settings.change_language": {
        "uz": "🌐 Tilni o'zgartirish",
        "ru": "🌐 Сменить язык",
    },
    "btn.share_phone": {
        "uz": "📱 Raqamimni yuborish",
        "ru": "📱 Отправить номер",
    },
    "btn.phone.skip": {
        "uz": "Keyinroq",
        "ru": "Позже",
    },
    "btn.menu.browse": {
        "uz": "💐 Gul buyurtma qilish",
        "ru": "💐 Заказать цветы",
    },
    "ibtn.browse.next": {"uz": "▶️ Yana", "ru": "▶️ Ещё"},
    "ibtn.browse.prev": {
        "uz": "◀️ Oldingi",
        "ru": "◀️ Назад",
    },
    "ibtn.browse.back_to_list": {
        "uz": "⬅️ Ro‘yxatga",
        "ru": "⬅️ К списку",
    },
    "ibtn.recipient_other": {
        "uz": "✍️ Boshqa odam",
        "ru": "✍️ Другой человек",
    },
    "btn.nav.back": {"uz": "⬅️ Orqaga", "ru": "⬅️ Назад"},
    "btn.nav.cancel": {"uz": "✖️ Bekor qilish", "ru": "✖️ Отмена"},
    "btn.menu.occasions": {"uz": "📅 Sanalarim", "ru": "📅 Мои даты"},
}

BUTTON_KEYS: Final = tuple(k for k in CATALOG if k.startswith("btn."))
