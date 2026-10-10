"""User-facing strings, uz + ru.

Every key must exist in every language; tests/test_i18n.py fails the build
otherwise. Keys whose value is a button LABEL are listed in BUTTON_KEYS, because
the handler-shadowing sweep probes the dispatcher with each of them.
"""

from __future__ import annotations

from typing import Final

LANGUAGES: Final = ("uz", "ru")
DEFAULT_LANGUAGE: Final = "uz"

#: The product's name inside a string (CP19). Never type the name itself:
#: `t()` fills this from Settings.brand_name, and tests/test_brand.py fails the
#: build on the name typed here. Uzbek suffixes attach directly ("{brand}ga"):
#: right after a name ending in a vowel or most consonants; a name ending in
#: k or q would want "-ka" / "-qa" there.
BRAND: Final = "{brand}"

CATALOG: Final[dict[str, dict[str, str]]] = {
    "start.choose_language": {
        "uz": "🌸 Assalomu alaykum! {brand}ga xush kelibsiz.\nQaysi tilda gaplashamiz?",
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
            "{brand} muhim sanalaringizni eslatib turadi va gul buyurtma "
            "berishga yordam beradi.\n\nSavollar bo'lsa, operatorga yozing."
        ),
        "ru": (
            "{brand} напоминает о ваших важных датах и помогает заказать "
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
    #
    # The last line is a TELEGRAM limitation, not ours, and it is stated here
    # because the customer cannot see the difference until it has already gone
    # wrong. `KeyboardButtonRequestLocation` sends the device's CURRENT
    # position and the Bot API offers no way to make it a place-picker --
    # choosing an arbitrary point needs Telegram's own attachment menu
    # (paperclip -> Location -> drag -> Send Selected Location), which no bot
    # can open. Someone ordering flowers for delivery to an address they are
    # not standing at is the ordinary case, not the edge one, so saying which
    # button does what BEFORE the choice is cheaper than an order that goes to
    # the wrong door. Typing the address already covers it.
    "order.choose_location": {
        "uz": "📍 Qayerga yetkazib beraylik?\n\n"
        "Joylashuvingizni yuboring — shunda kuryer aniq topadi. "
        "Yoki manzilni o‘zingiz yozing.\n\n"
        "ℹ️ Tugma siz hozir turgan joyni yuboradi. "
        "Agar boshqa manzilni belgilamoqchi bo‘lsangiz, matn orqali yozing.",
        "ru": "📍 Куда доставить?\n\n"
        "Отправьте локацию — курьеру будет точнее. "
        "Или напишите адрес сами.\n\n"
        "ℹ️ Кнопка отправляет место, где вы сейчас находитесь. "
        "Если нужен другой адрес, напишите его текстом.",
    },
    "ibtn.location_text": {"uz": "✍️ Manzil yozish", "ru": "✍️ Написать адрес"},
    # The pin goes FIRST in the keyboard and says what it is for, not what
    # it is called.
    "ibtn.location_pin": {
        "uz": "📍 Joylashuvni yuborish (tezroq)",
        "ru": "📍 Отправить локацию (быстрее)",
    },
    # Said plainly, and immediately followed by the date picker. The customer
    # did nothing wrong and loses nothing but the date -- which is why the
    # second sentence promises the rest is kept.
    "order.date_filled": {
        "uz": "😔 Afsuski, {date} kuni joylar tugadi.\n"
        "Boshqa kunni tanlang — qolgan javoblaringiz saqlanadi.",
        "ru": "😔 К сожалению, на {date} мест больше нет.\n"
        "Выберите другой день — остальные ответы сохранены.",
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
    # --- CP13. The shop acts on the card ---------------------------------
    # The buttons carry no order id in their LABEL, only in their callback
    # data, so the same two strings serve every card ever posted.
    "ibtn.confirm_order": {
        "uz": "✅ Qabul qilindi",
        "ru": "✅ Принят",
    },
    "ibtn.reject_order": {
        "uz": "❌ Rad etish",
        "ru": "❌ Отклонить",
    },
    # Named in the group, where several admins can see it, so it says WHICH
    # order it is waiting on -- two rejections in flight at once would
    # otherwise be two identical prompts.
    "group.reason_prompt": {
        "uz": "#{id} — rad etish sababini yozing:",
        "ru": "#{id} — напишите причину отказа:",
    },
    # A BUTTON, not the typed "Bekor qilish" nav already understands: nav
    # answers with a CUSTOMER reply keyboard, and this conversation happens
    # in the shop's own group. See ChatGateMiddleware.
    "ibtn.abort_reject": {
        "uz": "↩️ Bekor qilish",
        "ru": "↩️ Отмена",
    },
    "group.reject_aborted": {
        "uz": "#{id} — rad etish bekor qilindi.",
        "ru": "#{id} — отклонение отменено.",
    },
    # Appended to the card itself rather than sent as a new message: the card
    # IS the record, and a group with a day of orders in it should read as a
    # list of outcomes, not a list of questions.
    "group.outcome.confirmed": {
        "uz": "✅ <b>Qabul qilindi</b>",
        "ru": "✅ <b>Принят</b>",
    },
    "group.outcome.rejected": {
        "uz": "❌ <b>Rad etildi</b>\nℹ️ Sabab: {reason}",
        "ru": "❌ <b>Отклонён</b>\nℹ️ Причина: {reason}",
    },
    # While a Reject prompt is open the chat gate lets this admin's next group
    # message through as the reason. So the prompt EXPIRES: an admin pulled
    # away mid-rejection must not have an unrelated message become one.
    "group.reason_expired": {
        "uz": "#{id} — kech qoldi. Rad etish uchun tugmani qayta bosing.",
        "ru": "#{id} — время истекло. Нажмите кнопку ещё раз.",
    },
    "group.already_handled": {
        "uz": "Bu buyurtma allaqachon ko‘rib chiqilgan.",
        "ru": "Этот заказ уже обработан.",
    },
    "group.order_missing": {
        "uz": "Buyurtma topilmadi.",
        "ru": "Заказ не найден.",
    },
    # CP19: the shop has a staff list and this person is not on it. Shown as
    # an alert to them alone, so the group is not told who tried.
    "group.not_staff": {
        "uz": "Buyurtmani faqat do‘kon egasi tanlagan xodimlar tasdiqlay yoki rad eta oladi.",
        "ru": "Подтверждать и отклонять заказы могут только сотрудники, выбранные владельцем.",
    },
    # The honest half of a best-effort notification. The shop decided; the
    # customer could not be reached. Saying so in the group is what turns a
    # silent failure into a phone call someone actually makes.
    "group.customer_not_notified": {
        "uz": "⚠️ Mijozga xabar bormadi — o‘zingiz qo‘ng‘iroq qiling.",
        "ru": "⚠️ Клиенту не дошло — позвоните сами.",
    },
    # --- CP13. What the CUSTOMER is told ---------------------------------
    # The whole reason this checkpoint was pulled forward: without these, an
    # order sits unconfirmed and the customer assumes it was accepted.
    "order.status.confirmed": {
        "uz": "✅ Buyurtmangiz #{id} qabul qilindi.",
        "ru": "✅ Ваш заказ #{id} принят.",
    },
    "order.status.rejected": {
        "uz": "❌ Afsuski, buyurtmangiz #{id} qabul qilinmadi.\nℹ️ Sabab: {reason}",
        "ru": "❌ К сожалению, ваш заказ #{id} отклонён.\nℹ️ Причина: {reason}",
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
    # --- shop-owner onboarding, on the PLATFORM bot ------------------------
    "owner.welcome": {
        "uz": (
            "🌸 Assalomu alaykum! Keling, do‘koningizni {brand}ga ulaymiz — bir necha "
            "daqiqa oladi.\n\n"
            "<b>1-qadam. O‘z botingizni yarating</b>\n"
            "1. Telegramda @BotFather ni oching.\n"
            "2. /newbot buyrug‘ini yuboring.\n"
            "3. Botga nom bering — mijozlaringiz ko‘radigan nom, masalan: <i>Lola Gullari</i>.\n"
            "4. Username tanlang — u <code>bot</code> bilan tugashi kerak, "
            "masalan: <code>lola_gullari_bot</code>.\n"
            "5. BotFather sizga <b>token</b> beradi — "
            "<code>123456789:AA...</code> ko‘rinishidagi uzun qator.\n\n"
            "O‘sha tokenni nusxalab, shu yerga yuboring.\n"
            "🔐 Token — botingizning kaliti, uni hech kimga bermang. Biz uni shifrlab "
            "saqlaymiz va xabaringizni o‘chirib yuboramiz."
        ),
        "ru": (
            "🌸 Здравствуйте! Давайте подключим ваш магазин к {brand} — это займёт пару "
            "минут.\n\n"
            "<b>Шаг 1. Создайте своего бота</b>\n"
            "1. Откройте в Telegram @BotFather.\n"
            "2. Отправьте команду /newbot.\n"
            "3. Дайте боту имя — его увидят ваши клиенты, например: <i>Lola Gullari</i>.\n"
            "4. Выберите username — он должен заканчиваться на <code>bot</code>, "
            "например: <code>lola_gullari_bot</code>.\n"
            "5. BotFather пришлёт <b>токен</b> — длинную строку вида "
            "<code>123456789:AA...</code>.\n\n"
            "Скопируйте токен и отправьте его сюда.\n"
            "🔐 Токен — это ключ от вашего бота, никому его не передавайте. Мы храним его "
            "в зашифрованном виде и удалим ваше сообщение."
        ),
    },
    "owner.token_invalid": {
        "uz": (
            "Bu bot tokeniga o‘xshamaydi. Token <code>123456789:AA...</code> ko‘rinishida "
            "bo‘ladi: raqamlar, ikki nuqta, keyin uzun harf-raqamlar qatori. @BotFather dagi "
            "xabardan to‘liq nusxalab yuboring."
        ),
        "ru": (
            "Это не похоже на токен бота. Токен выглядит как <code>123456789:AA...</code>: "
            "цифры, двоеточие и длинная строка букв и цифр. Скопируйте его целиком из "
            "сообщения @BotFather."
        ),
    },
    "owner.token_taken": {
        "uz": (
            "Bu bot allaqachon boshqa do‘konga ulangan. Har bir do‘kon uchun alohida bot "
            "kerak — @BotFather da /newbot bilan yangisini yarating va uning tokenini yuboring."
        ),
        "ru": (
            "Этот бот уже подключён к другому магазину. Каждому магазину нужен свой бот — "
            "создайте новый через /newbot в @BotFather и отправьте его токен."
        ),
    },
    "owner.token_saved": {
        "uz": (
            "✅ Token qabul qilindi va shifrlab saqlandi. Xavfsizlik uchun xabaringizni o‘chirdim."
        ),
        "ru": (
            "✅ Токен принят и сохранён в зашифрованном виде. Для безопасности я удалил "
            "ваше сообщение."
        ),
    },
    "owner.token_rejected": {
        "uz": (
            "Telegram bu tokenni qabul qilmadi — u eskirgan yoki noto‘g‘ri nusxalangan "
            "bo‘lishi mumkin. @BotFather dan tokenni qaytadan nusxalab yuboring."
        ),
        "ru": (
            "Telegram не принял этот токен — возможно, он устарел или скопирован с ошибкой. "
            "Скопируйте токен из @BotFather заново и отправьте сюда."
        ),
    },
    "admin.link": {
        "uz": (
            "🔐 Boshqaruv paneliga kirish havolasi ({minutes} daqiqa, bir martalik):\n{url}\n\n"
            "Hech kimga yubormang."
        ),
        "ru": (
            "🔐 Ссылка для входа в панель управления ({minutes} мин, одноразовая):\n{url}\n\n"
            "Никому её не пересылайте."
        ),
        "en": "🔐 Admin panel login link ({minutes} min, single use):\n{url}\n\nDo not forward it.",
    },
    "admin.link_refused": {
        "uz": "Hozircha yangi havola berilmaydi — bir ozdan keyin qayta urinib ko‘ring.",
        "ru": "Сейчас новую ссылку выдать нельзя — попробуйте чуть позже.",
        "en": "No new link right now; try again in a few minutes.",
    },
    "admin.unavailable": {
        "uz": "Boshqaruv paneli faqat HTTPS orqali ishlaydi va hali sozlanmagan.",
        "ru": "Панель управления работает только по HTTPS и ещё не настроена.",
        "en": "The admin panel works only over HTTPS and is not set up yet.",
    },
    "premium.locked": {
        "uz": (
            "⭐ Bu — sovg‘a: ⭐ belgili dizaynlar, musiqa va suratlar shu do‘kondan "
            "birinchi buyurtmangiz tasdiqlangach ochiladi. Hozircha boshqa dizayn tanlang."
        ),
        "ru": (
            "⭐ Это подарок: дизайны со ⭐, музыка и фото открываются после того, как "
            "магазин подтвердит ваш первый заказ. Пока выберите другой дизайн."
        ),
        "en": (
            "⭐ This is a gift: the ⭐ designs, music and photos unlock once this shop "
            "confirms your first order. For now, pick another design."
        ),
    },
    "shop.paused": {
        "uz": (
            "🌙 Do‘kon vaqtincha ishlamayapti. Tez orada qaytamiz — sanalaringiz va "
            "sahifalaringiz saqlanib qoladi."
        ),
        "ru": ("🌙 Магазин временно не работает. Скоро вернёмся — ваши даты и страницы сохранены."),
        "en": "🌙 The shop is closed for now. We'll be back soon; your dates and pages are kept.",
    },
    "owner.not_configured": {
        "uz": (
            "⚠️ Hozircha yangi do‘kon ulab bo‘lmaydi — platforma sozlanmagan. Keyinroq "
            "urinib ko‘ring."
        ),
        "ru": "⚠️ Сейчас подключить магазин нельзя — платформа не настроена. Попробуйте позже.",
    },
    "owner.branding_ask": {
        "uz": "<b>2-qadam. Brend</b>\nSizda allaqachon Telegram kanal va do‘kon logotipi bormi?",
        "ru": "<b>Шаг 2. Бренд</b>\nУ вас уже есть Telegram-канал и логотип магазина?",
    },
    "owner.name_ask": {
        "uz": "Do‘koningiz nomini yozing — mijozlar uni shunday ko‘radi.",
        "ru": "Напишите название магазина — так его увидят клиенты.",
    },
    "owner.name_invalid": {
        "uz": "Nom 1 dan 200 belgigacha bo‘lishi kerak. Qaytadan yozing.",
        "ru": "Название должно быть от 1 до 200 символов. Напишите ещё раз.",
    },
    "owner.logo_enhance": {
        "uz": (
            "Logotipingizni yanada chiroyli qilish uchun uni ChatGPT (yoki boshqa AI rasm "
            "vositasi)ga yuklang va shu so‘rovni yuboring:\n\n"
            '<code>Here is the logo of my flower shop "{name}". Keep its design, colors '
            "and lettering, but make it cleaner and sharper: crisp vector-style edges, "
            "balanced spacing, legible even at 64x64 px. Give me a square version for a "
            "Telegram channel avatar and a version on a transparent background.</code>"
        ),
        "ru": (
            "Чтобы улучшить логотип, загрузите его в ChatGPT (или другой AI-генератор "
            "изображений) и отправьте этот запрос:\n\n"
            '<code>Here is the logo of my flower shop "{name}". Keep its design, colors '
            "and lettering, but make it cleaner and sharper: crisp vector-style edges, "
            "balanced spacing, legible even at 64x64 px. Give me a square version for a "
            "Telegram channel avatar and a version on a transparent background.</code>"
        ),
    },
    "owner.logo_generate": {
        "uz": (
            "Logotip yaratish uchun shu so‘rovni ChatGPT (yoki boshqa AI rasm vositasi)ga "
            "yuboring:\n\n"
            '<code>Design a logo for a flower shop called "{name}". Style: modern, elegant '
            "and minimal, with a single flower or petal motif and soft, fresh colors. The "
            'name "{name}" must be spelled exactly and be clearly legible. Square '
            "composition that still reads at 64x64 px as a Telegram channel avatar; plain "
            "background, plus a version on a transparent background.</code>\n\n"
            "Kanalingiz hali yo‘q bo‘lsa, Telegramda yangi kanal oching va shu logotipni "
            "qo‘ying."
        ),
        "ru": (
            "Чтобы создать логотип, отправьте этот запрос в ChatGPT (или другой "
            "AI-генератор изображений):\n\n"
            '<code>Design a logo for a flower shop called "{name}". Style: modern, elegant '
            "and minimal, with a single flower or petal motif and soft, fresh colors. The "
            'name "{name}" must be spelled exactly and be clearly legible. Square '
            "composition that still reads at 64x64 px as a Telegram channel avatar; plain "
            "background, plus a version on a transparent background.</code>\n\n"
            "Если канала ещё нет, создайте новый канал в Telegram и поставьте этот логотип."
        ),
    },
    "owner.channel_ask": {
        "uz": (
            "<b>3-qadam. Kanal</b>\n"
            "1. Kanalingizni oching → Boshqaruv → Administratorlar → Administrator qo‘shish.\n"
            "2. Hozir yaratgan botingizni toping va uni <b>administrator</b> qiling.\n"
            "3. Keyin shu yerga kanal usernameni (masalan <code>@lola_gullari</code>) "
            "yuboring yoki kanaldagi istalgan postni shu yerga forward qiling."
        ),
        "ru": (
            "<b>Шаг 3. Канал</b>\n"
            "1. Откройте канал → Управление → Администраторы → Добавить администратора.\n"
            "2. Найдите только что созданного бота и сделайте его <b>администратором</b>.\n"
            "3. Затем отправьте сюда username канала (например <code>@lola_gullari</code>) "
            "или перешлите сюда любой пост из канала."
        ),
    },
    "owner.channel_unreadable": {
        "uz": (
            "Kanalni aniqlay olmadim. Kanal usernameni <code>@</code> bilan yuboring "
            "(masalan <code>@lola_gullari</code>) yoki kanaldan bir postni forward qiling."
        ),
        "ru": (
            "Не удалось определить канал. Отправьте username канала с <code>@</code> "
            "(например <code>@lola_gullari</code>) или перешлите пост из канала."
        ),
    },
    "owner.channel_not_found": {
        "uz": (
            "Botingiz bu kanalni ko‘ra olmayapti. Username to‘g‘riligini tekshiring, botni "
            "kanalga administrator qilib qo‘shing va qayta yuboring."
        ),
        "ru": (
            "Ваш бот не видит этот канал. Проверьте username, добавьте бота в канал "
            "администратором и отправьте ещё раз."
        ),
    },
    "owner.channel_not_admin": {
        "uz": (
            "Botingiz kanalda administrator emas. Uni administrator qiling — aks holda yangi "
            "postlarni ko‘rmaydi — va qayta yuboring."
        ),
        "ru": (
            "Ваш бот не администратор канала. Сделайте его администратором — иначе он не "
            "увидит новые посты — и отправьте ещё раз."
        ),
    },
    "owner.channel_wrong_type": {
        "uz": "Bu kanal emas. Mahsulotlaringiz joylanadigan Telegram <b>kanal</b>ni yuboring.",
        "ru": "Это не канал. Отправьте Telegram-<b>канал</b>, где будут ваши товары.",
    },
    "owner.telegram_unreachable": {
        "uz": "Telegram hozir javob bermayapti. Bir daqiqadan so‘ng qayta yuboring.",
        "ru": "Telegram сейчас не отвечает. Отправьте ещё раз через минуту.",
    },
    "owner.channel_ok": {
        "uz": "✅ Kanal ulandi: <b>{title}</b>",
        "ru": "✅ Канал подключён: <b>{title}</b>",
    },
    "owner.posting_guide": {
        "uz": (
            "<b>Mahsulotni qanday joylash kerak</b>\n"
            "Kanaldagi post mahsulotga aylanadi, agar:\n"
            "• postda <b>rasm</b> bo‘lsa — faqat matnli postlar mahsulot bo‘lmaydi;\n"
            "• izohda kamida bitta <b>heshteg</b> bo‘lsa: <code>#atirgul</code>, "
            "<code>#buket</code>. Heshtegsiz post qo‘shilmaydi, faqat raqamdan iborat teg "
            "(<code>#450000</code>) heshteg hisoblanmaydi.\n"
            "Izohning <b>birinchi qatori</b> — mahsulot nomi. <b>Narx</b>ni "
            "<code>so‘m</code> (yoki <code>сум</code>, <code>UZS</code>) bilan yoki "
            "<code>Narxi:</code> dan keyin yozing — shunda bot uni aniq biladi; yorliqsiz "
            "raqam taxmin sifatida ko‘rsatiladi, «Narxi kelishiladi» esa narxsiz qoladi.\n\n"
            "Namuna:\n<code>Qizil atirgul buketi 51 ta\n"
            "Narxi: 450 000 so'm\n#atirgul #buket</code>\n\n"
            "• Albom (bir nechta rasm) — bitta mahsulot; izohni albomdagi rasmlardan biriga "
            "yozing.\n"
            "• Postni tahrirlasangiz, mahsulot yangilanadi; barcha heshteglarni o‘chirsangiz, "
            "mahsulot yashiriladi.\n"
            "• Bot faqat administrator bo‘lganidan <b>keyingi</b> postlarni ko‘radi."
        ),
        "ru": (
            "<b>Как публиковать товары</b>\n"
            "Пост в канале становится товаром, если:\n"
            "• в посте есть <b>фото</b> — текстовые посты товаром не становятся;\n"
            "• в подписи есть хотя бы один <b>хэштег</b>: <code>#atirgul</code>, "
            "<code>#buket</code>. Пост без хэштега не добавляется, а тег из одних цифр "
            "(<code>#450000</code>) хэштегом не считается.\n"
            "<b>Первая строка</b> подписи — название товара. <b>Цену</b> пишите с "
            "<code>so‘m</code> (или <code>сум</code>, <code>UZS</code>) или после "
            "<code>Narxi:</code> — тогда бот поймёт её точно; число без подписи "
            "показывается как примерное, а «Narxi kelishiladi» — без цены.\n\n"
            "Пример:\n<code>Qizil atirgul buketi 51 ta\n"
            "Narxi: 450 000 so'm\n#atirgul #buket</code>\n\n"
            "• Альбом (несколько фото) — один товар; подпись добавьте к любому фото альбома.\n"
            "• Если отредактировать пост, товар обновится; если удалить все хэштеги, товар "
            "скроется.\n"
            "• Бот видит только посты, опубликованные <b>после</b> того, как он стал "
            "администратором."
        ),
    },
    "owner.group_ask": {
        "uz": (
            "<b>4-qadam. Buyurtmalar guruhi</b>\n"
            "Yangi buyurtmalar shu guruhga keladi.\n"
            "1. Telegram guruhingizga botingizni qo‘shing va uni <b>administrator</b> "
            "qiling.\n"
            "2. Keyin pastdagi «Guruhni tanlash» tugmasini bosib, o‘sha guruhni tanlang."
        ),
        "ru": (
            "<b>Шаг 4. Группа для заказов</b>\n"
            "Новые заказы будут приходить в эту группу.\n"
            "1. Добавьте бота в свою Telegram-группу и сделайте его <b>администратором</b>.\n"
            "2. Затем нажмите кнопку «Выбрать группу» ниже и выберите эту группу."
        ),
    },
    "owner.group_test_message": {
        "uz": "✅ {brand}: bu do‘konning yangi buyurtmalari shu guruhga keladi.",
        "ru": "✅ {brand}: новые заказы этого магазина будут приходить в эту группу.",
    },
    "owner.group_not_found": {
        "uz": (
            "Botingiz bu guruhda yo‘q. Uni guruhga qo‘shib, administrator qiling va qayta tanlang."
        ),
        "ru": (
            "Вашего бота нет в этой группе. Добавьте его, сделайте администратором и "
            "выберите снова."
        ),
    },
    "owner.group_not_admin": {
        "uz": "Botingiz guruhda administrator emas. Uni administrator qiling va qayta tanlang.",
        "ru": "Ваш бот не администратор группы. Сделайте его администратором и выберите снова.",
    },
    "owner.group_cannot_post": {
        "uz": (
            "Botingiz guruhga xabar yoza olmadi. Guruh sozlamalarida botga xabar yuborishga "
            "ruxsat bering va qayta tanlang."
        ),
        "ru": (
            "Ваш бот не смог написать в группу. Разрешите ему отправлять сообщения в "
            "настройках группы и выберите снова."
        ),
    },
    "owner.group_wrong_type": {
        "uz": "Bu guruh emas. Buyurtmalar keladigan Telegram <b>guruh</b>ni tanlang.",
        "ru": "Это не группа. Выберите Telegram-<b>группу</b> для заказов.",
    },
    "owner.group_ok": {
        "uz": "✅ Guruh ulandi: <b>{title}</b>",
        "ru": "✅ Группа подключена: <b>{title}</b>",
    },
    "owner.phone_ask": {
        "uz": (
            "<b>5-qadam. Telefon raqamingiz</b>\n"
            "Siz bilan bog‘lanishimiz uchun raqamingizni yuboring — tugma orqali yoki yozib."
        ),
        "ru": (
            "<b>Шаг 5. Ваш номер телефона</b>\n"
            "Отправьте номер, чтобы мы могли с вами связаться — кнопкой или вручную."
        ),
    },
    "owner.done": {
        "uz": (
            "🎉 Tayyor! <b>{name}</b> do‘koni ulandi.\n"
            "Botingiz ishlayapti: mijozlar unga yoza oladi, kanaldagi yangi postlar "
            "katalogga qo‘shiladi, buyurtmalar esa guruhingizga keladi."
        ),
        "ru": (
            "🎉 Готово! Магазин <b>{name}</b> подключён.\n"
            "Ваш бот работает: клиенты могут ему писать, новые посты канала попадают в "
            "каталог, а заказы приходят в вашу группу."
        ),
    },
    "owner.cancelled": {
        "uz": "Bekor qilindi, hech narsa saqlanmadi. Qaytadan boshlash uchun /start yuboring.",
        "ru": "Отменено, ничего не сохранено. Чтобы начать заново, отправьте /start.",
    },
    "owner.resume": {
        "uz": "Davom etamiz — to‘xtagan joyingizdan:",
        "ru": "Продолжаем с того места, где вы остановились:",
    },
    "owner.idle": {
        "uz": "Yangi do‘kon ulash uchun /start yuboring.",
        "ru": "Чтобы подключить новый магазин, отправьте /start.",
    },
    "btn.owner.pick_group": {"uz": "👥 Guruhni tanlash", "ru": "👥 Выбрать группу"},
    # --- the staff list, on the platform bot (CP19) -------------------------
    "staff.pick_shop": {
        "uz": "Qaysi do‘konning xodimlari?",
        "ru": "Сотрудники какого магазина?",
    },
    "staff.title": {
        "uz": "👥 <b>{shop}</b>: buyurtmani kim tasdiqlaydi",
        "ru": "👥 <b>{shop}</b>: кто подтверждает заказы",
    },
    "staff.empty": {
        "uz": (
            "Ro‘yxat bo‘sh, shuning uchun guruhdagi har kim buyurtmani tasdiqlay yoki "
            "rad eta oladi.\n\nBirinchi xodimni qo‘shsangiz, buni faqat ro‘yxatdagilar "
            "va siz qila olasiz."
        ),
        "ru": (
            "Список пуст, поэтому подтвердить или отклонить заказ может любой участник "
            "группы.\n\nКогда вы добавите первого сотрудника, это смогут делать только "
            "люди из списка и вы."
        ),
    },
    "staff.listed": {
        "uz": "Buyurtmani faqat shu ro‘yxatdagilar va do‘kon egalari tasdiqlay oladi:\n{names}",
        "ru": "Подтверждать заказы могут только люди из этого списка и владельцы:\n{names}",
    },
    "staff.add_ask": {
        "uz": ("Pastdagi tugma bilan xodimni tanlang yoki uning Telegram ID raqamini yuboring."),
        "ru": "Выберите сотрудника кнопкой ниже или пришлите его Telegram ID.",
    },
    "staff.added": {
        "uz": "✅ {name} ro‘yxatga qo‘shildi.",
        "ru": "✅ {name} добавлен(а) в список.",
    },
    "staff.already": {
        "uz": "{name} ro‘yxatda bor edi.",
        "ru": "{name} уже в списке.",
    },
    "staff.removed": {
        "uz": "{name} ro‘yxatdan olindi.",
        "ru": "{name} удалён(а) из списка.",
    },
    "staff.not_listed": {
        "uz": "Bu odam ro‘yxatda yo‘q edi.",
        "ru": "Этого человека не было в списке.",
    },
    "staff.refused.not_owner": {
        "uz": "Bu do‘kon sizniki emas.",
        "ru": "Это не ваш магазин.",
    },
    "staff.refused.bad_id": {
        "uz": "Bu Telegram ID emas. Raqamni tekshirib, qayta yuboring.",
        "ru": "Это не Telegram ID. Проверьте число и пришлите ещё раз.",
    },
    "staff.refused.is_owner": {
        "uz": "Bu do‘kon egasi: egalar buyurtmani doim tasdiqlay oladi.",
        "ru": "Это владелец магазина: владельцы всегда могут подтверждать заказы.",
    },
    "staff.refused.full": {
        "uz": "Ro‘yxatda {max} kishidan ko‘p bo‘lmaydi. Avval kimnidir olib tashlang.",
        "ru": "В списке не больше {max} человек. Сначала удалите кого-нибудь.",
    },
    "btn.staff.pick": {"uz": "👤 Xodimni tanlash", "ru": "👤 Выбрать сотрудника"},
    "ibtn.staff.add": {"uz": "➕ Xodim qo‘shish", "ru": "➕ Добавить сотрудника"},
    "ibtn.staff.remove": {"uz": "✖️ {name}", "ru": "✖️ {name}"},
    # --- the date plan (CP17) ----------------------------------------------
    "pages.ask_plan": {
        "uz": (
            "Uchrashuv rejasini qo'shasizmi? «Ha» deyishsa, joy va vaqtni "
            "sizning variantlaringizdan tanlashadi."
        ),
        "ru": (
            "Добавить план встречи? Если ответят «Да», выберут место и время из ваших вариантов."
        ),
    },
    "ibtn.pages.plan_add": {
        "uz": "📍 Ha, joy va vaqt qo'shaman",
        "ru": "📍 Да, добавлю место и время",
    },
    "ibtn.pages.plan_skip": {
        "uz": "Rejasiz",
        "ru": "Без плана",
    },
    "ibtn.pages.plan_remove": {
        "uz": "🗑 Rejani olib tashlash",
        "ru": "🗑 Убрать план",
    },
    "pages.enter_place": {
        "uz": "Joy variantini yozing ({n}/{max}) — masalan, «Kino» yoki «Bog'da sayr».",
        "ru": ("Напишите вариант места ({n}/{max}) — например, «Кино» или «Прогулка в парке»."),
    },
    "pages.place_added": {
        "uz": "✅ Qo'shildi: {place}",
        "ru": "✅ Добавлено: {place}",
    },
    "pages.place_duplicate": {
        "uz": "Bu joy allaqachon bor.",
        "ru": "Такое место уже есть.",
    },
    "ibtn.pages.more_place": {
        "uz": "➕ Yana joy",
        "ru": "➕ Ещё место",
    },
    "ibtn.pages.places_done": {
        "uz": "➡️ Endi vaqt",
        "ru": "➡️ Теперь время",
    },
    "pages.choose_slot_month": {
        "uz": "Vaqt varianti ({n}/{max}): qaysi oy?",
        "ru": "Вариант времени ({n}/{max}): какой месяц?",
    },
    "pages.slot_added": {
        "uz": "✅ Qo'shildi: {when}",
        "ru": "✅ Добавлено: {when}",
    },
    "pages.slot_duplicate": {
        "uz": "Bu vaqt allaqachon bor.",
        "ru": "Такое время уже есть.",
    },
    "pages.slot_day_over": {
        "uz": "Bu kunda vaqt qolmadi — boshqa kunni tanlang.",
        "ru": "В этот день время уже прошло — выберите другой.",
    },
    "ibtn.pages.more_slot": {
        "uz": "➕ Yana vaqt",
        "ru": "➕ Ещё время",
    },
    "ibtn.pages.slots_done": {
        "uz": "✅ Rejani saqlash",
        "ru": "✅ Сохранить план",
    },
    "ibtn.pages.f_plan": {
        "uz": "📍 Uchrashuv rejasi",
        "ru": "📍 План встречи",
    },
    "pages.detail_choice": {
        "uz": "📍 Tanlandi: {place}, {when}",
        "ru": "📍 Выбрано: {place}, {when}",
    },
    "pages.notify_yes_plan": {
        "uz": "🎉 Ha! Joy: {place}. Sana: {when}.\n\nSavol: «{question}»",
        "ru": "🎉 Да! Место: {place}. Дата: {when}.\n\nВопрос: «{question}»",
    },
    "pages.notify_yes_unchosen": {
        "uz": (
            "🎉 «{question}» savolingizga «Ha» deb javob berishdi! Joy va "
            "vaqtni hali tanlashmadi — tanlashsa, alohida xabar beraman."
        ),
        "ru": (
            "🎉 На вопрос «{question}» ответили «Да»! Место и время пока "
            "не выбраны — когда выберут, я напишу отдельно."
        ),
    },
    "pages.notify_choice_later": {
        "uz": "📍 Joy va vaqt tanlandi! Joy: {place}. Sana: {when}.",
        "ru": "📍 Место и время выбраны! Место: {place}. Дата: {when}.",
    },
    # --- the Foto design's photo (CP17) -------------------------------------
    "pages.ask_photo": {
        "uz": (
            "📷 Bitta rasm yuboring — u sahifaning tepasida, ramkada "
            "turadi. Rasmdan joylashuv va boshqa yashirin ma'lumotlar "
            "olib tashlanadi."
        ),
        "ru": (
            "📷 Пришлите одно фото — оно будет в рамке вверху страницы. "
            "Геолокация и другие скрытые данные из фото удаляются."
        ),
    },
    "ibtn.pages.photo_skip": {
        "uz": "⏭ Rasmsiz",
        "ru": "⏭ Без фото",
    },
    "pages.photo_received": {
        "uz": "🖼 Rasm olindi.",
        "ru": "🖼 Фото получено.",
    },
    "pages.photo_too_big": {
        "uz": "Rasm juda katta (10 MB gacha). Boshqasini yuboring.",
        "ru": "Фото слишком большое (до 10 МБ). Пришлите другое.",
    },
    "pages.photo_send_as_photo": {
        "uz": "Rasmni «rasm» sifatida yuboring (fayl emas) yoki o'tkazib yuboring.",
        "ru": "Отправьте снимок как фото (не файлом) или пропустите.",
    },
    "pages.photo_refused": {
        "uz": (
            "Bu rasmni saqlab bo'lmadi — sahifa rasmsiz yaratildi. Keyin "
            "«Tahrirlash»dan qo'shishingiz mumkin."
        ),
        "ru": (
            "Это фото сохранить не удалось — страница создана без него. "
            "Его можно добавить потом в «Изменить»."
        ),
    },
    "ibtn.pages.f_photo": {
        "uz": "🖼 Rasm",
        "ru": "🖼 Фото",
    },
    # --- an invitation's photo gallery (CP17) -------------------------------
    "pages.ask_gallery": {
        "uz": (
            "📷 Suratlarni yuboring — har birini alohida xabar qilib, "
            "{max} tagacha (hozir {n}/{max}). Birinchisi «Foto» dizaynida "
            "ramkaga tushadi. Joylashuv va boshqa yashirin ma'lumotlar "
            "olib tashlanadi."
        ),
        "ru": (
            "📷 Пришлите фото — каждое отдельным сообщением, до {max} "
            "(сейчас {n}/{max}). Первое в дизайне «Фото» встанет в рамку. "
            "Геолокация и другие скрытые данные удаляются."
        ),
    },
    "pages.gallery_added": {
        "uz": "🖼 Qo'shildi: {n}/{max}. Yana yuboring yoki «Tayyor»ni bosing.",
        "ru": "🖼 Добавлено: {n}/{max}. Пришлите ещё или нажмите «Готово».",
    },
    "pages.gallery_full": {
        "uz": (
            "Suratlar to'ldi ({max}/{max}). Yangidan boshlash uchun «Hammasini o'chirish»ni bosing."
        ),
        "ru": ("Галерея заполнена ({max}/{max}). Чтобы начать заново, нажмите «Удалить все»."),
    },
    "pages.gallery_cleared": {
        "uz": "🗑 Suratlar o'chirildi. Yangilarini yuborishingiz mumkin ({max} tagacha).",
        "ru": "🗑 Фото удалены. Можно прислать новые (до {max}).",
    },
    "pages.photo_unreadable": {
        "uz": "Bu rasmni o'qib bo'lmadi. Boshqasini yuboring.",
        "ru": "Это фото не удалось прочитать. Пришлите другое.",
    },
    "ibtn.pages.photo_clear": {
        "uz": "🗑 Hammasini o'chirish",
        "ru": "🗑 Удалить все",
    },
    "ibtn.pages.photo_done": {
        "uz": "✅ Tayyor",
        "ru": "✅ Готово",
    },
    "ibtn.pages.f_gallery": {
        "uz": "🖼 Suratlar",
        "ru": "🖼 Фото",
    },
    # --- a taklifnoma's sections (CP17) -------------------------------------
    "ibtn.pages.f_colors": {
        "uz": "🎨 Ranglar",
        "ru": "🎨 Цвета",
    },
    "ibtn.pages.f_countdown": {
        "uz": "⏳ Taymer: {state}",
        "ru": "⏳ Таймер: {state}",
    },
    "ibtn.pages.f_show_gallery": {
        "uz": "🖼 Galereya: {state}",
        "ru": "🖼 Галерея: {state}",
    },
    "ibtn.pages.colors_none": {
        "uz": "🚫 Ranglarsiz",
        "ru": "🚫 Без цветов",
    },
    "pages.ask_colors": {
        "uz": (
            "🎨 Kiyinish uslubi uchun ranglarni tanlang ({max} tagacha), keyin «Tayyor»ni bosing."
        ),
        "ru": "🎨 Выберите цвета дресс-кода (до {max}), затем нажмите «Готово».",
    },
    "pages.colors_max": {
        "uz": "{max} tagacha rang tanlash mumkin.",
        "ru": "Можно выбрать до {max} цветов.",
    },
    "pages.edit_program_hint": {
        "uz": (
            "Har bir bandni alohida qatorga yozing, vaqti bilan: «18:00 "
            "Mehmonlarni kutib olish». 8 qatorgacha."
        ),
        "ru": ("Каждый пункт — с новой строки, со временем: «18:00 Встреча гостей». До 8 строк."),
    },
    # --- the wishes wall (CP17) ---------------------------------------------
    "ibtn.pages.f_wishes": {
        "uz": "💌 Tilaklar: {state}",
        "ru": "💌 Пожелания: {state}",
    },
    "ibtn.pages.f_wishes_list": {
        "uz": "📖 Tilaklarni ko'rish",
        "ru": "📖 Смотреть пожелания",
    },
    "pages.wishes_list": {
        "uz": ("💌 Mehmonlar tilaklari (eng yangilari). 🙈 — sahifadan yashirish, 👁 — qaytarish."),
        "ru": "💌 Пожелания гостей (самые новые). 🙈 — скрыть со страницы, 👁 — вернуть.",
    },
    "pages.wishes_none": {
        "uz": (
            "💌 Hali tilaklar yo'q. «Tilaklar» yoqilgan bo'lsa, mehmonlar "
            "sahifada tilak qoldira oladi."
        ),
        "ru": (
            "💌 Пожеланий пока нет. Если «Пожелания» включены, гости "
            "смогут оставить их на странице."
        ),
    },
    # --- the Konvert seal (CP17) --------------------------------------------
    "pages.ask_seal": {
        "uz": (
            "🔏 Muhrga qanday harflar bosilsin? Masalan: A&M (5 "
            "belgigacha). Yoki o'tkazib yuboring — ismlarning bosh "
            "harflari qo'yiladi."
        ),
        "ru": (
            "🔏 Какие буквы выдавить на печати? Например: A&M (до 5 "
            "знаков). Или пропустите — будут инициалы имён."
        ),
    },
    "ibtn.pages.seal_skip": {
        "uz": "⏭ Bosh harflar bilan",
        "ru": "⏭ Инициалы имён",
    },
    "pages.seal_invalid": {
        "uz": "Faqat harflar va «&» belgisi, {max} tagacha. Masalan: A&M",
        "ru": "Только буквы и знак «&», до {max}. Например: A&M",
    },
    "ibtn.pages.f_seal": {
        "uz": "🔏 Muhr harflari",
        "ru": "🔏 Буквы на печати",
    },
    # --- music (CP17) -------------------------------------------------------
    "ibtn.pages.f_music": {
        "uz": "🎵 Musiqa: {state}",
        "ru": "🎵 Музыка: {state}",
    },
    "ibtn.pages.music_none": {
        "uz": "🔇 Musiqasiz",
        "ru": "🔇 Без музыки",
    },
    "pages.ask_music": {
        "uz": (
            "🎵 Sahifa uchun kuy tanlang. U o'z-o'zidan chalinmaydi — "
            "mehmon tugmani bosgandagina yangraydi. Kuylar {brand} uchun "
            "yozilgan, litsenziyasi ochiq."
        ),
        "ru": (
            "🎵 Выберите мелодию для страницы. Она не играет сама — только "
            "когда гость нажмёт кнопку. Мелодии написаны для {brand}, "
            "лицензия открытая."
        ),
    },
    "pages.track_bahor": {
        "uz": "Bahor",
        "ru": "Весна",
    },
    "pages.track_oqshom": {
        "uz": "Oqshom",
        "ru": "Вечер",
    },
    "pages.track_tantana": {
        "uz": "Tantana",
        "ru": "Торжество",
    },
    # --- Uzrnoma, the apology letter (CP17) ---------------------------------
    "ibtn.pages.apology": {
        "uz": "🕊 Uzrnoma",
        "ru": "🕊 Письмо-извинение",
    },
    "pages.ask_apology": {
        "uz": (
            "✍️ Uzr so'zlaringizni yozing — o'z so'zlaringiz bilan, {max} "
            "belgigacha. Sahifada xat bo'lib turadi."
        ),
        "ru": (
            "✍️ Напишите извинение своими словами, до {max} знаков. На странице оно будет письмом."
        ),
    },
    "pages.ask_notify_apology": {
        "uz": "Kechirishganda sizga xabar beraymi?",
        "ru": "Сообщить вам, когда вас простят?",
    },
    "pages.confirm_apology": {
        "uz": (
            "🕊 <b>Uzrnoma</b>\n\n«{letter}»\n\nSahifa tili: "
            "{lang_name}\nDizayn: {template}\nXabar berish: {notify}"
        ),
        "ru": (
            "🕊 <b>Письмо-извинение</b>\n\n«{letter}»\n\nЯзык страницы: "
            "{lang_name}\nДизайн: {template}\nСообщить: {notify}"
        ),
    },
    "pages.notify_forgiven": {
        "uz": "🕊 Kechirdi! Uzrnomangiz qabul qilindi.\n\n«{letter}»",
        "ru": "🕊 Вас простили! Ваше письмо-извинение принято.\n\n«{letter}»",
    },
    "pages.answer_forgiven": {
        "uz": "🕊 Javob: «Kechirdim»! ({when})",
        "ru": "🕊 Ответ: «Прощаю»! ({when})",
    },
    "pages.detail_apology": {
        "uz": (
            "🕊 <b>{letter}</b>\n\n🔗 {url}\n👀 Ochishlar: {views}\n🌸 Do'kon "
            "havolasi bosilgan: {clicks}\n{answer}\n⏳ {expires} gacha"
        ),
        "ru": (
            "🕊 <b>{letter}</b>\n\n🔗 {url}\n👀 Открытий: {views}\n🌸 Переходов в "
            "магазин: {clicks}\n{answer}\n⏳ до {expires}"
        ),
    },
    "ibtn.pages.f_letter": {
        "uz": "✍️ Xat matni",
        "ru": "✍️ Текст письма",
    },
    # --- editing a page (CP17) ---------------------------------------------
    "ibtn.pages.edit": {
        "uz": "✏️ Tahrirlash",
        "ru": "✏️ Изменить",
    },
    "pages.edit_menu": {
        "uz": "Nimani o'zgartiramiz? Havola o'zgarmaydi — uni olganlar yangisini ko'radi.",
        "ru": "Что меняем? Ссылка останется прежней — у кого она есть, увидят новое.",
    },
    "pages.edit_locked": {
        "uz": (
            "🔒 Bu sahifaga javob berildi, endi uni o'zgartirib bo'lmaydi: "
            "javob aynan shu savolga berilgan."
        ),
        "ru": (
            "🔒 На эту страницу уже ответили, менять её больше нельзя: "
            "ответ дан именно на этот вопрос."
        ),
    },
    "pages.edit_current": {
        "uz": "Hozir:\n<i>{current}</i>\n\nYangisini yozing ({max} belgigacha).",
        "ru": "Сейчас:\n<i>{current}</i>\n\nНапишите новый вариант (до {max} символов).",
    },
    "pages.edit_empty_now": {
        "uz": "(bo'sh)",
        "ru": "(пусто)",
    },
    "pages.edit_contact_hint": {
        "uz": (
            "Bu matnni sahifada hamma ko'radi. Telefon raqamni faqat o'zingiz xohlasangiz yozing."
        ),
        "ru": (
            "Этот текст видят все, у кого есть ссылка. Номер телефона "
            "пишите, только если сами этого хотите."
        ),
    },
    "pages.edit_location": {
        "uz": "Yangi nuqtani 📎 → «Joylashuv» orqali yuboring yoki xaritani olib tashlang.",
        "ru": "Отправьте новую точку через 📎 → «Геопозиция» или уберите карту.",
    },
    "pages.edit_saved": {
        "uz": "✅ Saqlandi. Havola o'sha:\n{url}",
        "ru": "✅ Сохранено. Ссылка та же:\n{url}",
    },
    "pages.edit_invalid": {
        "uz": "Buni saqlab bo'lmadi.",
        "ru": "Это сохранить не получилось.",
    },
    "ibtn.pages.edit_reset": {
        "uz": "↩️ Tayyor matnga qaytarish",
        "ru": "↩️ Вернуть готовый текст",
    },
    "ibtn.pages.edit_clear": {
        "uz": "🧹 Olib tashlash",
        "ru": "🧹 Убрать",
    },
    "ibtn.pages.edit_back": {
        "uz": "↩️ Orqaga",
        "ru": "↩️ Назад",
    },
    "ibtn.pages.edit_done": {
        "uz": "✅ Tayyor",
        "ru": "✅ Готово",
    },
    "ibtn.pages.f_title": {
        "uz": "📝 Sarlavha",
        "ru": "📝 Заголовок",
    },
    "ibtn.pages.f_name_1": {
        "uz": "👤 Ism",
        "ru": "👤 Имя",
    },
    "ibtn.pages.f_groom": {
        "uz": "🤵 Kuyov ismi",
        "ru": "🤵 Имя жениха",
    },
    "ibtn.pages.f_bride": {
        "uz": "👰 Kelin ismi",
        "ru": "👰 Имя невесты",
    },
    "ibtn.pages.f_message": {
        "uz": "💬 Matn",
        "ru": "💬 Текст",
    },
    "ibtn.pages.f_event_at": {
        "uz": "📅 Sana va vaqt",
        "ru": "📅 Дата и время",
    },
    "ibtn.pages.f_venue": {
        "uz": "📍 Manzil",
        "ru": "📍 Место",
    },
    "ibtn.pages.f_location": {
        "uz": "🗺 Xarita",
        "ru": "🗺 Карта",
    },
    "ibtn.pages.f_dress_code": {
        "uz": "👗 Kiyinish uslubi",
        "ru": "👗 Дресс-код",
    },
    "ibtn.pages.f_program": {
        "uz": "📋 Dastur",
        "ru": "📋 Программа",
    },
    "ibtn.pages.f_contact": {
        "uz": "📞 Aloqa",
        "ru": "📞 Контакт",
    },
    "ibtn.pages.f_closing": {
        "uz": "✨ Yakuniy so'z",
        "ru": "✨ Финальная строка",
    },
    "ibtn.pages.f_rsvp": {
        "uz": "✅ RSVP: {state}",
        "ru": "✅ RSVP: {state}",
    },
    "ibtn.pages.f_template": {
        "uz": "🎨 Dizayn",
        "ru": "🎨 Дизайн",
    },
    "ibtn.pages.f_lang": {
        "uz": "🌐 Til",
        "ru": "🌐 Язык",
    },
    "ibtn.pages.f_question": {
        "uz": "❓ Savol",
        "ru": "❓ Вопрос",
    },
    "ibtn.pages.f_notify": {
        "uz": "🔔 Xabar: {state}",
        "ru": "🔔 Уведомить: {state}",
    },
    # --- Ha/Yo'q pages and taklifnomas -------------------------------------
    "btn.menu.pages": {"uz": "💌 Taklifnoma · Ha/Yo'q", "ru": "💌 Приглашения · Да/Нет"},
    "pages.menu": {
        "uz": (
            "Nima yaratamiz?\n\n"
            "💍 <b>Ha/Yo'q sahifa</b> — bitta savol, «Yo'q» tugmasi esa qochib ketadi 😄\n"
            "💌 <b>Taklifnoma</b> — to'y, tug'ilgan kun va boshqa tadbirlar uchun chiroyli "
            "havola.\n\nTayyor havolani Telegram orqali yuborasiz."
        ),
        "ru": (
            "Что создаём?\n\n"
            "💍 <b>Страница «Да/Нет»</b> — один вопрос, а кнопка «Нет» убегает 😄\n"
            "💌 <b>Приглашение</b> — красивая ссылка на свадьбу, день рождения и другие "
            "события.\n\nГотовую ссылку отправляете через Telegram."
        ),
    },
    "ibtn.pages.yesno": {"uz": "💍 Ha/Yo'q sahifa", "ru": "💍 Страница «Да/Нет»"},
    "ibtn.pages.invite": {"uz": "💌 Taklifnoma", "ru": "💌 Приглашение"},
    "ibtn.pages.mine": {"uz": "📂 Mening sahifalarim", "ru": "📂 Мои страницы"},
    "pages.unavailable": {
        "uz": "Bu xizmat hali ishga tushmagan. Tez orada!",
        "ru": "Эта функция ещё не запущена. Скоро!",
    },
    "pages.choose_lang": {
        "uz": "Sahifa qaysi tilda bo'lsin?",
        "ru": "На каком языке будет страница?",
    },
    "pages.choose_question": {
        "uz": "Qaysi savolni beramiz?",
        "ru": "Какой вопрос задаём?",
    },
    "ibtn.pages.custom_question": {"uz": "✏️ O'zim yozaman", "ru": "✏️ Напишу свой"},
    "pages.enter_question": {
        "uz": "Savolingizni yozing ({max} belgigacha).",
        "ru": "Напишите свой вопрос (до {max} символов).",
    },
    "pages.text_empty": {
        "uz": "Matnni yozing — tugma emas. Qaytadan urinib ko'ring.",
        "ru": "Напишите текст — не кнопку. Попробуйте ещё раз.",
    },
    "pages.text_trimmed": {
        "uz": "Matn {max} belgigacha qisqartirildi.",
        "ru": "Текст сокращён до {max} символов.",
    },
    "pages.choose_template": {
        "uz": "Dizaynni tanlang. Hammasini oldindan ko'rish:\n{gallery}",
        "ru": "Выберите дизайн. Посмотреть все заранее:\n{gallery}",
    },
    "pages.ask_notify": {
        "uz": "«Ha» deb javob berishsa, sizga xabar beraymi?",
        "ru": "Сообщить вам, когда ответят «Да»?",
    },
    "ibtn.pages.notify_yes": {"uz": "🔔 Ha, xabar bering", "ru": "🔔 Да, сообщите"},
    "ibtn.pages.notify_no": {"uz": "🔕 Shart emas", "ru": "🔕 Не нужно"},
    "pages.confirm_yesno": {
        "uz": (
            "Tekshiring:\n\n❓ <b>{question}</b>\n🌐 Til: {lang_name}\n🎨 Dizayn: {template}\n"
            "🔔 Xabar berish: {notify}\n📍 Reja: {plan}\n\nYaratamizmi?"
        ),
        "ru": (
            "Проверьте:\n\n❓ <b>{question}</b>\n🌐 Язык: {lang_name}\n🎨 Дизайн: {template}\n"
            "🔔 Уведомить: {notify}\n📍 План: {plan}\n\nСоздаём?"
        ),
    },
    "ibtn.pages.create": {"uz": "✅ Yaratish", "ru": "✅ Создать"},
    "ibtn.pages.cancel": {"uz": "❌ Bekor qilish", "ru": "❌ Отмена"},
    "pages.created": {
        "uz": (
            "Tayyor! 🎉 Mana havola:\n\n{url}\n\n"
            "Uni Telegram'da kimga xohlasangiz yuboring. Sahifa {expires} gacha ochiq turadi."
        ),
        "ru": (
            "Готово! 🎉 Вот ссылка:\n\n{url}\n\n"
            "Отправьте её в Telegram кому хотите. Страница открыта до {expires}."
        ),
    },
    "ibtn.pages.open": {"uz": "🔗 Ochish", "ru": "🔗 Открыть"},
    "ibtn.pages.share": {"uz": "📤 Ulashish", "ru": "📤 Поделиться"},
    "pages.limit_daily": {
        "uz": "Bugun {n} ta sahifa yaratdingiz — bu kunlik chegara. Ertaga yana urinib ko'ring.",
        "ru": "Сегодня вы создали {n} страниц — это дневной лимит. Попробуйте завтра.",
    },
    "pages.limit_live": {
        "uz": "Sizda {n} ta faol sahifa bor. Yangisi uchun eskisini o'chiring.",
        "ru": "У вас {n} активных страниц. Удалите старую, чтобы создать новую.",
    },
    "pages.cancelled": {"uz": "Bekor qilindi.", "ru": "Отменено."},
    "pages.choose_event": {"uz": "Qanday tadbir?", "ru": "Какое мероприятие?"},
    "ibtn.event.wedding": {"uz": "💍 To'y", "ru": "💍 Свадьба"},
    "ibtn.event.nikoh": {"uz": "🤍 Nikoh to'yi", "ru": "🤍 Никах"},
    "ibtn.event.fotiha": {"uz": "💐 Fotiha to'yi", "ru": "💐 Фатиха-туй"},
    "ibtn.event.birthday": {"uz": "🎂 Tug'ilgan kun", "ru": "🎂 День рождения"},
    "ibtn.event.beshik": {"uz": "👶 Beshik to'yi", "ru": "👶 Бешик-туй"},
    "ibtn.event.sunnat": {"uz": "🎊 Sunnat to'yi", "ru": "🎊 Суннат-туй"},
    "ibtn.event.anniversary": {"uz": "🥂 Yubiley", "ru": "🥂 Юбилей"},
    "ibtn.event.graduation": {"uz": "🎓 Bitiruv kechasi", "ru": "🎓 Выпускной"},
    "ibtn.event.corporate": {"uz": "🏢 Korporativ", "ru": "🏢 Корпоратив"},
    "ibtn.event.other": {"uz": "✨ Boshqa tadbir", "ru": "✨ Другое событие"},
    "pages.enter_couple_1": {
        "uz": "Kuyovning ismini yozing ({max} belgigacha).",
        "ru": "Напишите имя жениха (до {max} символов).",
    },
    "pages.enter_couple_2": {
        "uz": "Endi kelinning ismini yozing.",
        "ru": "Теперь имя невесты.",
    },
    "pages.enter_name_single": {
        "uz": "Kim uchun tadbir? Ismini yozing — masalan, «Malika» yoki «Aliyevlar oilasi».",
        "ru": "Для кого праздник? Напишите имя — например, «Малика» или «Семья Алиевых».",
    },
    "pages.choose_month": {"uz": "Tadbir qaysi oyda?", "ru": "В каком месяце?"},
    "pages.choose_day": {"uz": "Qaysi kuni?", "ru": "Какого числа?"},
    "pages.choose_hour": {"uz": "Soat nechada boshlanadi?", "ru": "Во сколько начало?"},
    "pages.choose_minute": {"uz": "Aniq vaqt:", "ru": "Точное время:"},
    "pages.enter_venue": {
        "uz": "Manzilni yozing: to'yxona, shahar, ko'cha ({max} belgigacha).",
        "ru": "Напишите место: зал, город, улица (до {max} символов).",
    },
    "pages.ask_location": {
        "uz": (
            "Joyni xaritada ko'rsatamizmi? 📎 → «Joylashuv» orqali kerakli nuqtani yuboring "
            "yoki o'tkazib yuboring."
        ),
        "ru": (
            "Показать место на карте? Отправьте нужную точку через 📎 → «Геопозиция» "
            "или пропустите."
        ),
    },
    "ibtn.pages.skip": {"uz": "⏭ O'tkazib yuborish", "ru": "⏭ Пропустить"},
    "pages.location_saved": {"uz": "📍 Joy saqlandi.", "ru": "📍 Место сохранено."},
    "pages.enter_message": {
        "uz": (
            "Mehmonlarga o'z so'zingizni yozasizmi? ({max} belgigacha) "
            "Yozmasangiz, tayyor chiroyli matn qo'yiladi."
        ),
        "ru": (
            "Напишете гостям своё обращение? (до {max} символов) "
            "Если нет — подставим готовый текст."
        ),
    },
    "pages.ask_rsvp": {
        "uz": (
            "Mehmonlar «Kelaman / Kela olmayman» deb javob bera olsinmi? "
            "Javoblar soni shu yerda, «Mening sahifalarim»da ko'rinadi."
        ),
        "ru": (
            "Дать гостям ответить «Приду / Не смогу»? "
            "Число ответов будет видно здесь, в «Мои страницы»."
        ),
    },
    "ibtn.pages.rsvp_yes": {"uz": "✅ Ha", "ru": "✅ Да"},
    "ibtn.pages.rsvp_no": {"uz": "Kerak emas", "ru": "Не нужно"},
    "pages.confirm_invite": {
        "uz": (
            "Tekshiring:\n\n{event}: <b>{names}</b>\n📅 {date}, {time}\n📍 {venue}{pin}\n"
            "💬 {message}\n✅ Javoblar (RSVP): {rsvp}\n🌐 Til: {lang_name}\n🎨 Dizayn: {template}"
            "\n\nYaratamizmi?"
        ),
        "ru": (
            "Проверьте:\n\n{event}: <b>{names}</b>\n📅 {date}, {time}\n📍 {venue}{pin}\n"
            "💬 {message}\n✅ Ответы (RSVP): {rsvp}\n🌐 Язык: {lang_name}\n🎨 Дизайн: {template}"
            "\n\nСоздаём?"
        ),
    },
    "pages.word_yes": {"uz": "ha", "ru": "да"},
    "pages.word_no": {"uz": "yo'q", "ru": "нет"},
    "pages.word_pin": {"uz": " (xaritada)", "ru": " (на карте)"},
    "pages.word_default_text": {"uz": "tayyor matn", "ru": "готовый текст"},
    "pages.mine_empty": {
        "uz": "Sizda hali sahifa yo'q. Yangisini yarating:",
        "ru": "У вас пока нет страниц. Создайте новую:",
    },
    "pages.mine_title": {"uz": "Sahifalaringiz:", "ru": "Ваши страницы:"},
    "pages.detail_yesno": {
        "uz": (
            "💍 <b>{question}</b>\n\n🔗 {url}\n👀 Ochishlar: {views}\n🌸 Do'kon havolasi "
            "bosilgan: {clicks}\n{answer}\n⏳ {expires} gacha"
        ),
        "ru": (
            "💍 <b>{question}</b>\n\n🔗 {url}\n👀 Открытий: {views}\n🌸 Переходов в магазин: "
            "{clicks}\n{answer}\n⏳ до {expires}"
        ),
    },
    "pages.answer_none": {"uz": "⏳ Hali javob yo'q", "ru": "⏳ Ответа пока нет"},
    "pages.answer_yes": {"uz": "✅ Javob: «Ha»! ({when})", "ru": "✅ Ответ: «Да»! ({when})"},
    "pages.detail_invite": {
        "uz": (
            "💌 <b>{names}</b> — {event}\n📅 {date}\n\n🔗 {url}\n👀 Ochishlar: {views}\n"
            "🌸 Do'kon havolasi bosilgan: {clicks}\n{rsvp}\n⏳ {expires} gacha"
        ),
        "ru": (
            "💌 <b>{names}</b> — {event}\n📅 {date}\n\n🔗 {url}\n👀 Открытий: {views}\n"
            "🌸 Переходов в магазин: {clicks}\n{rsvp}\n⏳ до {expires}"
        ),
    },
    "pages.rsvp_counts": {
        "uz": "✅ Kelaman: {coming} (jami {guests} kishi)\n❌ Kela olmayman: {not_coming}",
        "ru": "✅ Придут: {coming} (всего {guests} чел.)\n❌ Не смогут: {not_coming}",
    },
    "pages.rsvp_off": {"uz": "RSVP o'chirilgan", "ru": "RSVP выключен"},
    "ibtn.pages.delete": {"uz": "🗑 O'chirish", "ru": "🗑 Удалить"},
    "ibtn.pages.really_delete": {"uz": "🗑 Ha, o'chirilsin", "ru": "🗑 Да, удалить"},
    "ibtn.pages.back_list": {"uz": "⬅️ Ro'yxatga", "ru": "⬅️ К списку"},
    "pages.confirm_delete": {
        "uz": "Sahifa o'chirilsinmi? Havola boshqa ochilmaydi, yozilgan matnlar o'chiriladi.",
        "ru": "Удалить страницу? Ссылка перестанет открываться, а текст будет стёрт.",
    },
    "pages.deleted": {"uz": "O'chirildi.", "ru": "Удалено."},
    "pages.gone": {"uz": "Bu sahifa topilmadi.", "ru": "Страница не найдена."},
    "pages.notify_yes": {
        "uz": (
            "🎉 Javob keldi! «{question}» savolingizga <b>«Ha»</b> deb javob berishdi 💖\n\n"
            "Bu kunni gullar bilan nishonlang 🌸"
        ),
        "ru": (
            "🎉 Есть ответ! На вопрос «{question}» ответили <b>«Да»</b> 💖\n\n"
            "Отметьте этот день цветами 🌸"
        ),
    },
}


# --- English (CP17) ----------------------------------------------------------
#
# English covers what an English-speaking customer needs to reach and use the
# Ha/Yo'q and taklifnoma flows -- first contact, the language choice, the main
# menu, settings, navigation -- and those flows themselves, completely. Every
# other key falls back to Uzbek through `t()`. A full English catalogue is a
# separate piece of work, recorded in docs/CHECKPOINTS.md (CP17).
#
# TRILINGUAL_KEYS is what tests/test_i18n_trilingual.py holds to uz + ru + en,
# together with every key of the page flows, so a new page-flow key that forgets
# English fails the build.
_EN: Final[dict[str, str]] = {
    "start.choose_language": "Hello! Welcome to {brand}. Which language shall we use?",
    "start.welcome_back": "Welcome back, {name}!",
    "language.saved": (
        "Great, we'll continue in English. Invitations and Yes/No pages are fully in "
        "English; a few other sections are still in Uzbek."
    ),
    "menu.title": "Main menu. What shall we do?",
    "settings.title": "Settings",
    "help.text": (
        "{brand} reminds you of important dates and helps you order flowers.\n\n"
        "If you have questions, write to the operator."
    ),
    "nav.cancelled": "Cancelled.",
    "nav.nothing_to_cancel": "Nothing to cancel.",
    "common.unknown": "Please choose one of the buttons below 🙂",
    "btn.menu.settings": "⚙️ Settings",
    "btn.menu.help": "ℹ️ Help",
    "btn.menu.browse": "💐 Order flowers",
    "btn.menu.occasions": "📅 My dates",
    "btn.menu.pages": "💌 Invitations · Yes/No",
    "btn.nav.back": "⬅️ Back",
    "btn.nav.cancel": "✖️ Cancel",
    "btn.settings.change_language": "🌐 Change language",
    "btn.language.uz": "🇺🇿 O'zbekcha",
    "btn.language.ru": "🇷🇺 Русский",
    "btn.language.en": "🇬🇧 English",
    # --- the page flows ---------------------------------------------------
    "pages.menu": (
        "What shall we make?\n\n"
        "💍 <b>Yes/No page</b> — one question, and the «No» button runs away 😄\n"
        "💌 <b>Invitation</b> — a beautiful link for a wedding, a birthday or any "
        "other event.\n\nYou send the finished link through Telegram."
    ),
    "ibtn.pages.yesno": "💍 Yes/No page",
    "ibtn.pages.invite": "💌 Invitation",
    "ibtn.pages.mine": "📂 My pages",
    "pages.unavailable": "This isn't available yet. Coming soon!",
    "pages.choose_lang": "Which language should the page be in?",
    "pages.choose_question": "Which question shall we ask?",
    "ibtn.pages.custom_question": "✏️ I'll write my own",
    "pages.enter_question": "Write your question (up to {max} characters).",
    "pages.text_empty": "Please type text, not a button. Try again.",
    "pages.text_trimmed": "The text was shortened to {max} characters.",
    "pages.choose_template": "Choose a design. Preview them all here:\n{gallery}",
    "pages.ask_notify": "Shall I tell you when they answer «Yes»?",
    "ibtn.pages.notify_yes": "🔔 Yes, tell me",
    "ibtn.pages.notify_no": "🔕 No need",
    "pages.confirm_yesno": (
        "Please check:\n\n❓ <b>{question}</b>\n🌐 Language: {lang_name}\n🎨 Design: {template}\n"
        "🔔 Notify me: {notify}\n📍 Plan: {plan}\n\nCreate it?"
    ),
    "ibtn.pages.create": "✅ Create",
    "ibtn.pages.cancel": "❌ Cancel",
    "pages.created": (
        "Done! 🎉 Here is the link:\n\n{url}\n\n"
        "Send it to anyone on Telegram. The page stays open until {expires}."
    ),
    "ibtn.pages.open": "🔗 Open",
    "ibtn.pages.share": "📤 Share",
    "pages.limit_daily": (
        "You've made {n} pages today — that's the daily limit. Try again tomorrow."
    ),
    "pages.limit_live": "You have {n} live pages. Delete an old one to make a new one.",
    "pages.cancelled": "Cancelled.",
    "pages.choose_event": "What kind of event?",
    "ibtn.event.wedding": "💍 Wedding",
    "ibtn.event.nikoh": "🤍 Nikah",
    "ibtn.event.fotiha": "💐 Engagement",
    "ibtn.event.birthday": "🎂 Birthday",
    "ibtn.event.beshik": "👶 Beshik toy",
    "ibtn.event.sunnat": "🎊 Sunnat toy",
    "ibtn.event.anniversary": "🥂 Anniversary",
    "ibtn.event.graduation": "🎓 Graduation",
    "ibtn.event.corporate": "🏢 Corporate",
    "ibtn.event.other": "✨ Other event",
    "pages.enter_couple_1": "Write the groom's name (up to {max} characters).",
    "pages.enter_couple_2": "Now the bride's name.",
    "pages.enter_name_single": (
        "Who is the event for? Write the name — for example «Malika» or «The Aliyev family»."
    ),
    "pages.choose_month": "Which month?",
    "pages.choose_day": "Which day?",
    "pages.choose_hour": "What time does it start?",
    "pages.choose_minute": "Exact time:",
    "pages.enter_venue": "Write the venue: hall, city, street (up to {max} characters).",
    "pages.ask_location": (
        "Show the place on a map? Send the point through 📎 → «Location», or skip."
    ),
    "ibtn.pages.skip": "⏭ Skip",
    "pages.location_saved": "📍 Location saved.",
    "pages.enter_message": (
        "Would you like to write your own words to the guests? (up to {max} characters) "
        "If not, a ready text will be used."
    ),
    "pages.ask_rsvp": (
        "Let guests answer «I'll be there / Can't make it»? The counts will show here, in "
        "«My pages»."
    ),
    "ibtn.pages.rsvp_yes": "✅ Yes",
    "ibtn.pages.rsvp_no": "No need",
    "pages.confirm_invite": (
        "Please check:\n\n{event}: <b>{names}</b>\n📅 {date}, {time}\n📍 {venue}{pin}\n"
        "💬 {message}\n✅ Replies (RSVP): {rsvp}\n🌐 Language: {lang_name}\n🎨 Design: {template}"
        "\n\nCreate it?"
    ),
    "pages.word_yes": "yes",
    "pages.word_no": "no",
    "pages.word_pin": " (on the map)",
    "pages.word_default_text": "ready text",
    "pages.mine_empty": "You have no pages yet. Make a new one:",
    "pages.mine_title": "Your pages:",
    "pages.detail_yesno": (
        "💍 <b>{question}</b>\n\n🔗 {url}\n👀 Opened: {views}\n🌸 Shop link taps: {clicks}\n"
        "{answer}\n⏳ until {expires}"
    ),
    "pages.answer_none": "⏳ No answer yet",
    "pages.answer_yes": "✅ Answer: «Yes»! ({when})",
    "pages.detail_invite": (
        "💌 <b>{names}</b> — {event}\n📅 {date}\n\n🔗 {url}\n👀 Opened: {views}\n"
        "🌸 Shop link taps: {clicks}\n{rsvp}\n⏳ until {expires}"
    ),
    "pages.rsvp_counts": (
        "✅ Coming: {coming} ({guests} people in all)\n❌ Can't come: {not_coming}"
    ),
    "pages.rsvp_off": "RSVP is off",
    "ibtn.pages.delete": "🗑 Delete",
    "ibtn.pages.really_delete": "🗑 Yes, delete it",
    "ibtn.pages.back_list": "⬅️ Back to the list",
    "pages.confirm_delete": (
        "Delete the page? The link will stop opening and the text will be erased."
    ),
    "pages.deleted": "Deleted.",
    "pages.gone": "This page was not found.",
    "pages.notify_yes": (
        "🎉 An answer! To «{question}» they said <b>«Yes»</b> 💖\n\n"
        "Celebrate the day with flowers 🌸"
    ),
}

# Editing a page (CP17).
_EN["ibtn.pages.edit"] = "✏️ Edit"
_EN["pages.edit_menu"] = (
    "What shall we change? The link stays the same — everyone who has it sees the new version."
)
_EN["pages.edit_locked"] = (
    "🔒 This page has been answered, so it can no longer be "
    "changed: the answer was given to exactly this question."
)
_EN["pages.edit_current"] = "Now:\n<i>{current}</i>\n\nWrite the new text (up to {max} characters)."
_EN["pages.edit_empty_now"] = "(empty)"
_EN["pages.edit_contact_hint"] = (
    "Everyone with the link sees this text. Add a phone number only if you want to."
)
_EN["pages.edit_location"] = "Send the new point through 📎 → «Location», or remove the map."
_EN["pages.edit_saved"] = "✅ Saved. Same link:\n{url}"
_EN["pages.edit_invalid"] = "That could not be saved."
_EN["ibtn.pages.edit_reset"] = "↩️ Back to the ready text"
_EN["ibtn.pages.edit_clear"] = "🧹 Remove"
_EN["ibtn.pages.edit_back"] = "↩️ Back"
_EN["ibtn.pages.edit_done"] = "✅ Done"
_EN["ibtn.pages.f_title"] = "📝 Title"
_EN["ibtn.pages.f_name_1"] = "👤 Name"
_EN["ibtn.pages.f_groom"] = "🤵 Groom's name"
_EN["ibtn.pages.f_bride"] = "👰 Bride's name"
_EN["ibtn.pages.f_message"] = "💬 Message"
_EN["ibtn.pages.f_event_at"] = "📅 Date and time"
_EN["ibtn.pages.f_venue"] = "📍 Venue"
_EN["ibtn.pages.f_location"] = "🗺 Map"
_EN["ibtn.pages.f_dress_code"] = "👗 Dress code"
_EN["ibtn.pages.f_program"] = "📋 Programme"
_EN["ibtn.pages.f_contact"] = "📞 Contact"
_EN["ibtn.pages.f_closing"] = "✨ Closing line"
_EN["ibtn.pages.f_rsvp"] = "✅ RSVP: {state}"
_EN["ibtn.pages.f_template"] = "🎨 Design"
_EN["ibtn.pages.f_lang"] = "🌐 Language"
_EN["ibtn.pages.f_question"] = "❓ Question"
_EN["ibtn.pages.f_notify"] = "🔔 Notify: {state}"

# The date plan (CP17).
_EN["pages.ask_plan"] = (
    "Add a date plan? If they say «Yes», they will pick a place and a time from your options."
)
_EN["ibtn.pages.plan_add"] = "📍 Yes, add places and times"
_EN["ibtn.pages.plan_skip"] = "No plan"
_EN["ibtn.pages.plan_remove"] = "🗑 Remove the plan"
_EN["pages.enter_place"] = (
    "Write a place option ({n}/{max}) — for example «Cinema» or «A walk in the park»."
)
_EN["pages.place_added"] = "✅ Added: {place}"
_EN["pages.place_duplicate"] = "That place is already there."
_EN["ibtn.pages.more_place"] = "➕ Another place"
_EN["ibtn.pages.places_done"] = "➡️ Now the times"
_EN["pages.choose_slot_month"] = "Time option ({n}/{max}): which month?"
_EN["pages.slot_added"] = "✅ Added: {when}"
_EN["pages.slot_duplicate"] = "That time is already there."
_EN["pages.slot_day_over"] = "That day has no time left — pick another."
_EN["ibtn.pages.more_slot"] = "➕ Another time"
_EN["ibtn.pages.slots_done"] = "✅ Save the plan"
_EN["ibtn.pages.f_plan"] = "📍 Date plan"
_EN["pages.detail_choice"] = "📍 Chosen: {place}, {when}"
_EN["pages.notify_yes_plan"] = "🎉 Yes! Place: {place}. Date: {when}.\n\nQuestion: «{question}»"
_EN["pages.notify_yes_unchosen"] = (
    "🎉 They answered «Yes» to «{question}»! No place or time is "
    "chosen yet — I'll write again when they choose."
)
_EN["pages.notify_choice_later"] = "📍 Place and time chosen! Place: {place}. Date: {when}."

# The Foto design's photo (CP17).
_EN["pages.ask_photo"] = (
    "📷 Send one photo — it goes in the frame at the top of the "
    "page. Location and other hidden data are removed from it."
)
_EN["ibtn.pages.photo_skip"] = "⏭ No photo"
_EN["pages.photo_received"] = "🖼 Photo received."
_EN["pages.photo_too_big"] = "That photo is too large (10 MB at most). Please send another."
_EN["pages.photo_send_as_photo"] = "Please send it as a photo (not a file), or skip."
_EN["pages.photo_refused"] = (
    "That photo could not be kept — the page was made without it. "
    "You can add one later under «Edit»."
)
_EN["ibtn.pages.f_photo"] = "🖼 Photo"

# an invitation's photo gallery (CP17).
_EN["pages.ask_gallery"] = (
    "📷 Send your photos — one per message, up to {max} (now "
    "{n}/{max}). In the Foto design the first one goes in the "
    "frame. Location and other hidden data are removed."
)
_EN["pages.gallery_added"] = "🖼 Added: {n}/{max}. Send another, or tap «Done»."
_EN["pages.gallery_full"] = "The gallery is full ({max}/{max}). Tap «Remove all» to start again."
_EN["pages.gallery_cleared"] = "🗑 The photos are gone. You can send new ones (up to {max})."
_EN["pages.photo_unreadable"] = "That photo could not be read. Please send another."
_EN["ibtn.pages.photo_clear"] = "🗑 Remove all"
_EN["ibtn.pages.photo_done"] = "✅ Done"
_EN["ibtn.pages.f_gallery"] = "🖼 Photos"

# a taklifnoma's sections (CP17).
_EN["ibtn.pages.f_colors"] = "🎨 Colours"
_EN["ibtn.pages.f_countdown"] = "⏳ Countdown: {state}"
_EN["ibtn.pages.f_show_gallery"] = "🖼 Gallery: {state}"
_EN["ibtn.pages.colors_none"] = "🚫 No colours"
_EN["pages.ask_colors"] = "🎨 Pick the dress-code colours (up to {max}), then tap «Done»."
_EN["pages.colors_max"] = "You can pick up to {max} colours."
_EN["pages.edit_program_hint"] = (
    "One item per line, with its time: «18:00 Guests arrive». Up to 8 lines."
)

# the wishes wall (CP17).
_EN["ibtn.pages.f_wishes"] = "💌 Wishes: {state}"
_EN["ibtn.pages.f_wishes_list"] = "📖 Read the wishes"
_EN["pages.wishes_list"] = (
    "💌 Your guests' wishes (newest first). 🙈 hides one from the page, 👁 brings it back."
)
_EN["pages.wishes_none"] = (
    "💌 No wishes yet. With «Wishes» switched on, guests can leave them on the page."
)

# the Konvert seal (CP17).
_EN["pages.ask_seal"] = (
    "🔏 Which letters should the wax seal carry? For example: A&M "
    "(up to 5). Or skip, and the names' initials are used."
)
_EN["ibtn.pages.seal_skip"] = "⏭ Use the initials"
_EN["pages.seal_invalid"] = "Letters and «&» only, up to {max}. For example: A&M"
_EN["ibtn.pages.f_seal"] = "🔏 Seal letters"

# music (CP17).
_EN["ibtn.pages.f_music"] = "🎵 Music: {state}"
_EN["ibtn.pages.music_none"] = "🔇 No music"
_EN["pages.ask_music"] = (
    "🎵 Pick a tune for the page. It never plays by itself — only "
    "when a guest taps the button. The tunes were written for "
    "{brand} and are openly licensed."
)
_EN["pages.track_bahor"] = "Spring"
_EN["pages.track_oqshom"] = "Evening"
_EN["pages.track_tantana"] = "Celebration"

# Uzrnoma, the apology letter (CP17).
_EN["ibtn.pages.apology"] = "🕊 Apology letter"
_EN["pages.ask_apology"] = (
    "✍️ Write your apology in your own words, up to {max} "
    "characters. It will be a letter on the page."
)
_EN["pages.ask_notify_apology"] = "Shall I tell you when you are forgiven?"
_EN["pages.confirm_apology"] = (
    "🕊 <b>Apology letter</b>\n\n«{letter}»\n\nPage language: "
    "{lang_name}\nDesign: {template}\nTell me: {notify}"
)
_EN["pages.notify_forgiven"] = "🕊 You are forgiven! Your apology was accepted.\n\n«{letter}»"
_EN["pages.answer_forgiven"] = "🕊 Answer: «I forgive you»! ({when})"
_EN["pages.detail_apology"] = (
    "🕊 <b>{letter}</b>\n\n🔗 {url}\n👀 Opened: {views}\n🌸 Taps to the "
    "shop: {clicks}\n{answer}\n⏳ until {expires}"
)
_EN["ibtn.pages.f_letter"] = "✍️ The letter"

CATALOG["btn.language.en"] = {"uz": "🇬🇧 English", "ru": "🇬🇧 English"}
for _key, _value in _EN.items():
    CATALOG[_key]["en"] = _value

TRILINGUAL_KEYS: Final = frozenset(_EN)

# After every key exists, English included: the sweep probes each label.
BUTTON_KEYS: Final = tuple(k for k in CATALOG if k.startswith("btn."))
