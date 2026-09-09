"""Reply keyboards, built from the i18n catalog."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, time

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from gulbot.bot.callbacks import (
    AddOccasionCB,
    BackCB,
    BrowsePageCB,
    BrowsePickCB,
    ConfirmCB,
    DayCB,
    EditOccasionCB,
    FlowerCB,
    MonthCB,
    OccasionActionCB,
    OccasionKindCB,
    OccasionTypeCB,
    OrderBackCB,
    OrderConfirmCB,
    OrderDateCB,
    OrderHourCB,
    OrderLocationCB,
    OrderRecipientCB,
    OrderStartCB,
    RecipientCB,
    RecipientListCB,
    ReminderCountCB,
    SendTimeCB,
    YearSkipCB,
    YesNoCB,
)
from gulbot.i18n import t
from gulbot.models.occasion import MAX_DAY_IN_MONTH, OccasionKind, OccasionType
from gulbot.models.recipient import FLOWER_PRESETS
from gulbot.utils.render import format_date_long


def _kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label) for label in row] for row in rows],
        resize_keyboard=True,
    )


def language_keyboard(lang: str, *, with_back: bool) -> ReplyKeyboardMarkup:
    rows = [[t("btn.language.uz", lang), t("btn.language.ru", lang)]]
    if with_back:
        rows.append([t("btn.nav.back", lang)])
    return _kb(rows)


def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """Ordering goes FIRST, on its own row.

    Until CP11 the only way to order was the button attached to a reminder,
    so a customer who wanted flowers on a day with nothing due could not buy
    any. It leads because it is the thing that earns money; dates are the
    thing that brings people back.
    """
    return _kb(
        [
            [t("btn.menu.browse", lang)],
            [t("btn.menu.occasions", lang)],
            [t("btn.menu.settings", lang), t("btn.menu.help", lang)],
        ]
    )


def settings_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return _kb([[t("btn.settings.change_language", lang)], [t("btn.nav.back", lang)]])


# --- inline keyboards for the occasion flow --------------------------------


def _back_button(lang: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=t("ibtn.back", lang), callback_data=BackCB(action="back").pack()
    )


def occasion_type_keyboard(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=t(f"occtype.{preset.value}", lang),
                callback_data=OccasionTypeCB(type=preset.value).pack(),
            )
        ]
        for preset in OccasionType
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def occasion_kind_keyboard(lang: str) -> InlineKeyboardMarkup:
    """What kind of date this is. One row per kind, plus Back."""
    rows = [
        [
            InlineKeyboardButton(
                text=t(f"occkind.{kind.value}", lang),
                callback_data=OccasionKindCB(kind=kind.value).pack(),
            )
        ]
        for kind in OccasionKind
    ]
    rows.append([_back_button(lang)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def month_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=t(f"month.{month}", lang), callback_data=MonthCB(month=month).pack()
        )
        for month in range(1, 13)
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([_back_button(lang)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def day_keyboard(lang: str, month: int) -> InlineKeyboardMarkup:
    """Built FROM the chosen month, so an impossible day is never offered.

    This is why Feb 30 and Apr 31 are structurally unreachable rather than
    merely validated after the fact.
    """
    last_day = MAX_DAY_IN_MONTH[month - 1]
    buttons = [
        InlineKeyboardButton(text=str(day), callback_data=DayCB(day=day).pack())
        for day in range(1, last_day + 1)
    ]
    rows = [buttons[i : i + 7] for i in range(0, len(buttons), 7)]
    rows.append([_back_button(lang)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def year_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.skip_year", lang),
                    callback_data=YearSkipCB(action="skip").pack(),
                )
            ],
            [_back_button(lang)],
        ]
    )


def confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.save", lang), callback_data=ConfirmCB(action="save").pack()
                ),
                InlineKeyboardButton(
                    text=t("ibtn.discard", lang),
                    callback_data=ConfirmCB(action="discard").pack(),
                ),
            ],
            [_back_button(lang)],
        ]
    )


def occasion_list_keyboard(lang: str, occasions: Sequence[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{t('ibtn.deactivate', lang)} {label}",
                callback_data=OccasionActionCB(action="deactivate", occasion_id=occasion_id).pack(),
            )
        ]
        for occasion_id, label in occasions
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.add_occasion", lang),
                callback_data=AddOccasionCB(action="start").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- recipients ------------------------------------------------------------


def yes_no_keyboard(lang: str, scope: str) -> InlineKeyboardMarkup:
    """Ha / Yo'q for the chained questions.

    `scope` is baked into the callback data so the two loops never share a
    trigger, which keeps the shadow sweep able to tell them apart.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.yes", lang),
                    callback_data=YesNoCB(scope=scope, answer="yes").pack(),
                ),
                InlineKeyboardButton(
                    text=t("ibtn.no", lang),
                    callback_data=YesNoCB(scope=scope, answer="no").pack(),
                ),
            ]
        ]
    )


def recipient_list_keyboard(
    lang: str, recipients: Sequence[tuple[int, str]]
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"👤 {label}",
                callback_data=RecipientCB(action="open", recipient_id=recipient_id).pack(),
            )
        ]
        for recipient_id, label in recipients
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.add_person", lang),
                callback_data=AddOccasionCB(action="start").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recipient_detail_keyboard(
    lang: str, recipient_id: int, occasions: Sequence[tuple[int, str]]
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"📅 {shown}",
                callback_data=EditOccasionCB(occasion_id=occasion_id).pack(),
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=OccasionActionCB(action="deactivate", occasion_id=occasion_id).pack(),
            ),
        ]
        for occasion_id, shown in occasions
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.add_date", lang),
                callback_data=RecipientCB(action="add_date", recipient_id=recipient_id).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.rename", lang),
                callback_data=RecipientCB(action="rename", recipient_id=recipient_id).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.deactivate", lang),
                callback_data=RecipientCB(action="deactivate", recipient_id=recipient_id).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.back", lang),
                callback_data=RecipientListCB(action="back").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def label_preset_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Presets plus an explicit "I will type it" branch, for renaming."""
    rows = [
        [
            InlineKeyboardButton(
                text=t(f"occtype.{preset.value}", lang),
                callback_data=OccasionTypeCB(type=preset.value).pack(),
            )
        ]
        for preset in OccasionType
        if preset is not OccasionType.CUSTOM
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.custom_label", lang),
                callback_data=OccasionTypeCB(type=OccasionType.CUSTOM.value).pack(),
            )
        ]
    )
    rows.append([_back_button(lang)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- preferences -----------------------------------------------------------
# All button-only. Nothing here opens a text-waiting state, so the shadow
# sweep's message surface does not grow.


def flower_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Three presets plus "Boshqa", which stores NULL."""
    rows = [
        [
            InlineKeyboardButton(
                text=t(f"flower.{preset}", lang),
                callback_data=FlowerCB(choice=preset).pack(),
            )
        ]
        for preset in FLOWER_PRESETS
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.flower_other", lang),
                callback_data=FlowerCB(choice="skip").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reminder_count_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(f"ibtn.count_{n}", lang),
                    callback_data=ReminderCountCB(value=str(n)).pack(),
                )
                for n in (1, 2, 3)
            ],
            [
                InlineKeyboardButton(
                    text=t("ibtn.skip", lang),
                    callback_data=ReminderCountCB(value="skip").pack(),
                )
            ],
        ]
    )


def send_time_keyboard(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=t(f"ibtn.time_{slot}", lang),
                callback_data=SendTimeCB(value=slot).pack(),
            )
        ]
        for slot in ("morning", "noon", "evening")
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.skip", lang),
                callback_data=SendTimeCB(value="skip").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- CP10: ordering --------------------------------------------------------


def order_button(lang: str, product_id: int, recipient_id: int = 0) -> InlineKeyboardMarkup:
    """The one button under a bouquet.

    `recipient_id` is 0 from the browse screen, where no occasion is behind
    the choice, and the reminder's recipient otherwise. Both callers attach
    the same button to the same flow.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.order_now", lang),
                    callback_data=OrderStartCB(
                        product_id=product_id, recipient_id=recipient_id
                    ).pack(),
                )
            ]
        ]
    )


def _order_back_row(lang: str) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            text=t("btn.nav.back", lang), callback_data=OrderBackCB(action="back").pack()
        )
    ]


def order_date_keyboard(lang: str, dates: Sequence[date], today: date) -> InlineKeyboardMarkup:
    """Only the dates the shop can actually deliver on.

    A date the shop is closed on, already at `daily_order_cap`, or past the
    same-day cutoff never appears -- rather than being offered and refused.
    """
    rows = [
        [
            InlineKeyboardButton(
                text=format_date_long(day.day, day.month, None, lang),
                callback_data=OrderDateCB(offset=(day - today).days).pack(),
            )
        ]
        for day in dates
    ]
    rows.append(_order_back_row(lang))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_hour_keyboard(lang: str, hours: Sequence[time]) -> InlineKeyboardMarkup:
    """Whole hours, three to a row. Already filtered by working hours and lead
    time, so every button shown is one the shop can honour."""
    buttons = [
        InlineKeyboardButton(
            text=f"{hour.hour:02d}:00", callback_data=OrderHourCB(hour=hour.hour).pack()
        )
        for hour in hours
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append(_order_back_row(lang))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_location_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Drop a pin, or write an address. The customer's choice -- the CHECK on
    `orders` is what guarantees exactly one of them is stored.

    THE PIN GOES FIRST. It is the better answer for both sides: the courier
    gets coordinates instead of an approximate address, and the customer taps
    once instead of typing. It was second, and the shop owner missed it
    entirely on a first pass through their own bot.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.location_pin", lang),
                    callback_data=OrderLocationCB(mode="pin").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("ibtn.location_text", lang),
                    callback_data=OrderLocationCB(mode="text").pack(),
                )
            ],
            _order_back_row(lang),
        ]
    )


def share_location_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """Telegram's native location button. It only exists on a REPLY keyboard,
    which is why this one step leaves the inline flow."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn.share_location", lang), request_location=True)],
            [KeyboardButton(text=t("btn.nav.cancel", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def share_phone_keyboard(lang: str, *, with_skip: bool) -> ReplyKeyboardMarkup:
    """Telegram's native contact button, which like the location one exists only
    on a REPLY keyboard.

    `with_skip` is the whole onboarding/order split in one flag: at onboarding a
    customer may decline and still use the reminder half of the product; at
    order time the courier needs a number, so the only ways out are giving one
    or cancelling.
    """
    rows = [[KeyboardButton(text=t("btn.share_phone", lang), request_contact=True)]]
    if with_skip:
        rows.append([KeyboardButton(text=t("btn.phone.skip", lang))])
    rows.append([KeyboardButton(text=t("btn.nav.cancel", lang))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def order_recipient_keyboard(lang: str, known_label: str) -> InlineKeyboardMarkup:
    """The name the bot already knows, or a way to type a different one.

    Shown only on the reminder path. The known label leads because it is
    right most of the time -- someone who set a reminder for their mother is
    usually sending the flowers to her.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=known_label[:ROW_LABEL_MAX],
                    callback_data=OrderRecipientCB(action="known").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("ibtn.recipient_other", lang),
                    callback_data=OrderRecipientCB(action="other").pack(),
                )
            ],
            _order_back_row(lang),
        ]
    )


def order_confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Nothing is written to `orders` until one of these is tapped."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.yes", lang), callback_data=OrderConfirmCB(action="submit").pack()
                ),
                InlineKeyboardButton(
                    text=t("ibtn.no", lang), callback_data=OrderConfirmCB(action="discard").pack()
                ),
            ],
            _order_back_row(lang),
        ]
    )


# --- CP11: browsing the catalogue ------------------------------------------


#: Inline button labels are read on a phone, in one line. A 200-character
#: product name has to be cut somewhere, and cutting it here rather than in the
#: name itself keeps the full text for the card the shop reads.
ROW_LABEL_MAX = 40


def browse_list_keyboard(
    lang: str,
    rows: Sequence[tuple[int, str]],
    *,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    """One button per bouquet, then a navigation row.

    Prev and Next appear only when they lead somewhere. A dead button that
    answers with nothing is worse than no button: the customer taps it twice
    before deciding the bot is broken.
    """
    keyboard: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=label[:ROW_LABEL_MAX],
                callback_data=BrowsePickCB(product_id=product_id).pack(),
            )
        ]
        for product_id, label in rows
    ]

    nav: list[InlineKeyboardButton] = []
    if has_prev:
        nav.append(
            InlineKeyboardButton(
                text=t("ibtn.browse.prev", lang),
                callback_data=BrowsePageCB(action="prev").pack(),
            )
        )
    if has_next:
        nav.append(
            InlineKeyboardButton(
                text=t("ibtn.browse.next", lang),
                callback_data=BrowsePageCB(action="next").pack(),
            )
        )
    if nav:
        keyboard.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def browse_product_keyboard(lang: str, product_id: int) -> InlineKeyboardMarkup:
    """Under the shop's own post: order it, or go back to the list.

    The order button is the SAME callback a reminder carries, so the order flow
    has one entry point rather than two that could drift.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.order_now", lang),
                    callback_data=OrderStartCB(product_id=product_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("ibtn.browse.back_to_list", lang),
                    callback_data=BrowsePageCB(action="close").pack(),
                )
            ],
        ]
    )
