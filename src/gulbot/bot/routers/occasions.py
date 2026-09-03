"""Recipients and their dates: list, chained add, minimal edit, deactivate.

The flow is recipient-first. A person is created once, then dates are chained
onto them:

    choosing_type -> [entering_label] -> choosing_month -> choosing_day
                  -> entering_year -> confirming
                  -> asking_more_dates --yes--> choosing_month (SAME recipient)
                                      --no---> asking_more_people
                                               --yes--> choosing_type (NEW person)
                                               --no---> done

Two loop-back edges, both button-only. Nothing is written until the customer
taps Ha on `confirming`, which restates the person, the type and the date.

The recipient row is created at CONFIRM, not at type-pick: creating it earlier
would leave an orphan person behind every abandoned flow.

Editing a date re-enters the SAME month -> day -> confirm sub-flow with
`editing_occasion_id` in the FSM data, rather than duplicating six states.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import (
    AddOccasionCB,
    BackCB,
    ConfirmCB,
    DayCB,
    EditOccasionCB,
    FlowerCB,
    MonthCB,
    OccasionActionCB,
    OccasionTypeCB,
    RecipientCB,
    RecipientListCB,
    ReminderCountCB,
    SendTimeCB,
    YearSkipCB,
    YesNoCB,
)
from gulbot.bot.keyboards import (
    confirm_keyboard,
    day_keyboard,
    flower_keyboard,
    label_preset_keyboard,
    main_menu_keyboard,
    month_keyboard,
    occasion_type_keyboard,
    recipient_detail_keyboard,
    recipient_list_keyboard,
    reminder_count_keyboard,
    send_time_keyboard,
    year_keyboard,
    yes_no_keyboard,
)
from gulbot.bot.states import AddOccasion, EditRecipient
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.customer import Customer
from gulbot.models.occasion import OccasionType
from gulbot.services.occasions import (
    create_occasion,
    deactivate_occasion,
    get_occasion,
    is_valid_month_day,
    is_valid_year,
    record_store_dates_consent,
    update_occasion_date,
)
from gulbot.services.preferences import (
    has_answered_reminder_preferences,
    set_preferred_hashtag,
    set_reminder_count,
    set_send_time,
)
from gulbot.services.recipients import (
    create_recipient,
    deactivate_recipient,
    get_recipient,
    list_recipient_occasions,
    list_recipients,
    rename_recipient,
)
from gulbot.utils.render import escape, format_date
from gulbot.utils.text import sanitize_label

OCCASIONS_LABELS = set(CATALOG["btn.menu.occasions"].values())


def _reply_target(callback: CallbackQuery) -> Message:
    """The message an inline callback should answer into.

    Telegram omits `message` for callbacks on messages older than 48 hours, so
    this is checked rather than assumed.
    """
    message = callback.message
    if not isinstance(message, Message):
        raise ValueError("callback has no reachable message")
    return message


def _type_name(lang: str, type_: str) -> str:
    return t(f"occtype.{type_}", lang)


# --- listing ---------------------------------------------------------------


async def _render_recipient_list(
    target: Message, session: AsyncSession, customer: Customer, lang: str
) -> None:
    recipients = await list_recipients(session, shop_id=customer.shop_id, customer_id=customer.id)
    if not recipients:
        await target.answer(
            t("recipients.empty", lang), reply_markup=recipient_list_keyboard(lang, [])
        )
        return
    await target.answer(
        t("recipients.list_title", lang),
        reply_markup=recipient_list_keyboard(lang, [(r.id, r.label) for r in recipients]),
    )


async def _render_recipient_detail(
    target: Message,
    session: AsyncSession,
    customer: Customer,
    lang: str,
    recipient_id: int,
) -> None:
    recipient = await get_recipient(
        session, shop_id=customer.shop_id, customer_id=customer.id, recipient_id=recipient_id
    )
    if recipient is None:
        await target.answer(t("recipients.not_found", lang))
        return
    occasions = await list_recipient_occasions(session, recipient_id=recipient.id)
    shown = [(o.id, format_date(o.day, o.month, o.year)) for o in occasions]
    dates = "\n".join(f"• {label}" for _, label in shown) or t("recipients.no_dates", lang)
    await target.answer(
        t("recipients.detail", lang, label=escape(recipient.label), dates=dates),
        reply_markup=recipient_detail_keyboard(lang, recipient.id, shown),
    )


async def show_recipients(
    message: Message, session: AsyncSession, customer: Customer, lang: str
) -> None:
    await _render_recipient_list(message, session, customer, lang)


async def back_to_list(
    callback: CallbackQuery, session: AsyncSession, customer: Customer, lang: str
) -> None:
    await callback.answer()
    await _render_recipient_list(_reply_target(callback), session, customer, lang)


async def open_recipient(
    callback: CallbackQuery,
    callback_data: RecipientCB,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    await _render_recipient_detail(
        _reply_target(callback), session, customer, lang, callback_data.recipient_id
    )


async def remove_recipient(
    callback: CallbackQuery,
    callback_data: RecipientCB,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    label = await deactivate_recipient(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        recipient_id=callback_data.recipient_id,
    )
    await callback.answer()
    target = _reply_target(callback)
    if label is None:
        await target.answer(t("recipients.not_found", lang))
        return
    await target.answer(t("recipients.deactivated", lang, label=escape(label)))
    await _render_recipient_list(target, session, customer, lang)


async def remove_occasion(
    callback: CallbackQuery,
    callback_data: OccasionActionCB,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    label = await deactivate_occasion(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        occasion_id=callback_data.occasion_id,
    )
    await callback.answer()
    target = _reply_target(callback)
    if label is None:
        await target.answer(t("occasions.not_found", lang))
        return
    await target.answer(t("occasions.deactivated", lang, label=escape(label)))
    await _render_recipient_list(target, session, customer, lang)


# --- add flow --------------------------------------------------------------


async def start_add(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.set_state(AddOccasion.choosing_type)
    await state.update_data(recipient_id=None, editing_occasion_id=None)
    await callback.answer()
    await _reply_target(callback).answer(
        t("occasions.choose_type", lang), reply_markup=occasion_type_keyboard(lang)
    )


async def begin_onboarding_chain(target: Message, state: FSMContext, lang: str) -> None:
    """Entry point used by first-contact onboarding, straight after language."""
    await state.set_state(AddOccasion.choosing_type)
    await state.update_data(onboarding=True, recipient_id=None, editing_occasion_id=None)
    await target.answer(t("occasions.choose_type", lang), reply_markup=occasion_type_keyboard(lang))


async def pick_type(
    callback: CallbackQuery, callback_data: OccasionTypeCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    target = _reply_target(callback)
    if callback_data.type == OccasionType.CUSTOM.value:
        await state.set_state(AddOccasion.entering_label)
        await target.answer(t("occasions.enter_label", lang))
        return
    await state.update_data(
        pending_type=callback_data.type, pending_label=_type_name(lang, callback_data.type)
    )
    await state.set_state(AddOccasion.choosing_month)
    await target.answer(t("occasions.choose_month", lang), reply_markup=month_keyboard(lang))


async def enter_label(message: Message, state: FSMContext, lang: str) -> None:
    raw = message.text or ""
    label = sanitize_label(raw)
    if not label:
        await message.answer(t("occasions.label_empty", lang))
        return
    if len(raw.strip()) > len(label):
        await message.answer(t("occasions.label_trimmed", lang))
    await state.update_data(pending_type=OccasionType.CUSTOM.value, pending_label=label)
    await state.set_state(AddOccasion.choosing_month)
    await message.answer(t("occasions.choose_month", lang), reply_markup=month_keyboard(lang))


async def add_date_for_recipient(
    callback: CallbackQuery,
    callback_data: RecipientCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    """Add a date to an EXISTING person, from their detail view."""
    recipient = await get_recipient(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        recipient_id=callback_data.recipient_id,
    )
    await callback.answer()
    target = _reply_target(callback)
    if recipient is None:
        await target.answer(t("recipients.not_found", lang))
        return
    await state.set_state(AddOccasion.choosing_month)
    await state.update_data(
        recipient_id=recipient.id,
        pending_label=recipient.label,
        pending_type=recipient.type,
        editing_occasion_id=None,
    )
    await target.answer(t("occasions.choose_month", lang), reply_markup=month_keyboard(lang))


async def edit_occasion_date(
    callback: CallbackQuery,
    callback_data: EditOccasionCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    """Re-enter the creation sub-flow, marked as an edit."""
    occasion = await get_occasion(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        occasion_id=callback_data.occasion_id,
    )
    await callback.answer()
    target = _reply_target(callback)
    if occasion is None:
        await target.answer(t("occasions.not_found", lang))
        return
    await state.set_state(AddOccasion.choosing_month)
    await state.update_data(
        recipient_id=occasion.recipient_id,
        pending_label=occasion.label,
        pending_type=occasion.type,
        editing_occasion_id=occasion.id,
    )
    await target.answer(t("occasions.choose_month", lang), reply_markup=month_keyboard(lang))


async def pick_month(
    callback: CallbackQuery, callback_data: MonthCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    await state.update_data(month=callback_data.month)
    await state.set_state(AddOccasion.choosing_day)
    await _reply_target(callback).answer(
        t("occasions.choose_day", lang), reply_markup=day_keyboard(lang, callback_data.month)
    )


async def pick_day(
    callback: CallbackQuery, callback_data: DayCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    data = await state.get_data()
    month = int(data["month"])
    target = _reply_target(callback)
    # The picker cannot offer an invalid day, so this can only fire on a forged
    # or replayed callback. Refuse rather than trust the client.
    if not is_valid_month_day(month, callback_data.day):
        await target.answer(t("occasions.choose_day", lang), reply_markup=day_keyboard(lang, month))
        return
    await state.update_data(day=callback_data.day)
    await state.set_state(AddOccasion.entering_year)
    await target.answer(t("occasions.enter_year", lang), reply_markup=year_keyboard(lang))


async def _go_to_confirm(
    answer_to: Message, state: FSMContext, lang: str, year: int | None
) -> None:
    await state.update_data(year=year)
    data = await state.get_data()
    await state.set_state(AddOccasion.confirming)
    summary = t(
        "occasions.confirm",
        lang,
        label=escape(str(data["pending_label"])),
        type_name=_type_name(lang, str(data["pending_type"])),
        date=format_date(int(data["day"]), int(data["month"]), year),
    )
    consent = t("occasions.consent", lang)
    await answer_to.answer(f"{summary}\n\n{consent}", reply_markup=confirm_keyboard(lang))


async def enter_year(message: Message, state: FSMContext, lang: str) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or len(raw) != 4:
        await message.answer(t("occasions.year_invalid", lang))
        return
    year = int(raw)
    data = await state.get_data()
    month, day = int(data["month"]), int(data["day"])
    if not 1900 <= year <= 2100:
        await message.answer(t("occasions.year_invalid", lang))
        return
    if not is_valid_year(year, month, day):
        await message.answer(t("occasions.year_not_leap", lang))
        return
    await _go_to_confirm(message, state, lang, year)


async def skip_year(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await _go_to_confirm(_reply_target(callback), state, lang, None)


async def _ask_more_dates(target: Message, state: FSMContext, lang: str, label: str) -> None:
    await state.set_state(AddOccasion.asking_more_dates)
    await target.answer(
        t("recipients.ask_more_dates", lang, label=escape(label)),
        reply_markup=yes_no_keyboard(lang, "dates"),
    )


async def confirm_save(
    callback: CallbackQuery,
    callback_data: ConfirmCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    target = _reply_target(callback)
    data: dict[str, Any] = await state.get_data()

    if callback_data.action == "discard":
        await state.clear()
        await target.answer(t("nav.cancelled", lang), reply_markup=main_menu_keyboard(lang))
        return

    month, day, year = int(data["month"]), int(data["day"]), data.get("year")
    editing_id = data.get("editing_occasion_id")

    if editing_id is not None:
        updated = await update_occasion_date(
            session,
            shop_id=customer.shop_id,
            customer_id=customer.id,
            occasion_id=int(editing_id),
            month=month,
            day=day,
            year=year,
        )
        recipient_id = int(data["recipient_id"])
        await state.clear()
        if not updated:
            await target.answer(t("occasions.not_found", lang))
            return
        await target.answer(t("occasions.date_updated", lang, date=format_date(day, month, year)))
        await _render_recipient_detail(target, session, customer, lang, recipient_id)
        return

    recipient_id_value = data.get("recipient_id")
    if recipient_id_value is None:
        recipient = await create_recipient(
            session,
            shop_id=customer.shop_id,
            customer_id=customer.id,
            label=str(data["pending_label"]),
            type_=str(data["pending_type"]),
        )
        recipient_id_value = recipient.id
        await state.update_data(recipient_id=recipient_id_value)

    occasion = await create_occasion(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        recipient_id=int(recipient_id_value),
        type_=str(data["pending_type"]),
        label=str(data["pending_label"]),
        month=month,
        day=day,
        year=year,
    )
    if occasion is None:
        await target.answer(t("occasions.duplicate", lang))
        await _ask_more_dates(target, state, lang, str(data["pending_label"]))
        return

    # Consent is recorded when the first date is stored, carrying the version of
    # the wording shown on the confirm screen above.
    await record_store_dates_consent(session, shop_id=customer.shop_id, customer_id=customer.id)
    await target.answer(
        t(
            "occasions.saved",
            lang,
            label=escape(occasion.label),
            date=format_date(occasion.day, occasion.month, occasion.year),
        )
    )
    await _ask_more_dates(target, state, lang, str(data["pending_label"]))


# --- the chained questions -------------------------------------------------


async def more_dates_yes(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    """Loop back into the date sub-flow for the SAME recipient."""
    await callback.answer()
    await state.update_data(editing_occasion_id=None)
    await state.set_state(AddOccasion.choosing_month)
    await _reply_target(callback).answer(
        t("occasions.choose_month", lang), reply_markup=month_keyboard(lang)
    )


async def _ask_more_people(target: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(AddOccasion.asking_more_people)
    await target.answer(
        t("recipients.ask_more_people", lang), reply_markup=yes_no_keyboard(lang, "people")
    )


async def more_dates_no(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    """Ask this person's flower preference, unless they already have one."""
    await callback.answer()
    target = _reply_target(callback)
    data = await state.get_data()
    recipient_id = data.get("recipient_id")

    recipient = (
        None
        if recipient_id is None
        else await get_recipient(
            session,
            shop_id=customer.shop_id,
            customer_id=customer.id,
            recipient_id=int(recipient_id),
        )
    )
    if recipient is None or recipient.preferred_hashtag is not None:
        await _ask_more_people(target, state, lang)
        return

    await state.set_state(AddOccasion.asking_flower)
    await target.answer(
        t("prefs.ask_flower", lang, label=escape(recipient.label)),
        reply_markup=flower_keyboard(lang),
    )


async def pick_flower(
    callback: CallbackQuery,
    callback_data: FlowerCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    """ "Boshqa" stores NULL: no preference is a valid answer, not a failure."""
    await callback.answer()
    data = await state.get_data()
    recipient_id = data.get("recipient_id")
    if recipient_id is not None:
        await set_preferred_hashtag(
            session,
            shop_id=customer.shop_id,
            customer_id=customer.id,
            recipient_id=int(recipient_id),
            hashtag=None if callback_data.choice == "skip" else callback_data.choice,
        )
    await _ask_more_people(_reply_target(callback), state, lang)


async def more_people_yes(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    """Loop back to the preset picker for a NEW person."""
    await callback.answer()
    await state.update_data(
        recipient_id=None, pending_label=None, pending_type=None, editing_occasion_id=None
    )
    await state.set_state(AddOccasion.choosing_type)
    await _reply_target(callback).answer(
        t("occasions.choose_type", lang), reply_markup=occasion_type_keyboard(lang)
    )


async def _finish_chain(target: Message, state: FSMContext, lang: str) -> None:
    data = await state.get_data()
    was_onboarding = bool(data.get("onboarding"))
    await state.clear()
    key = "recipients.onboarding_done" if was_onboarding else "menu.title"
    await target.answer(t(key, lang), reply_markup=main_menu_keyboard(lang))


async def more_people_no(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    """Ask the customer-level preferences once, then finish."""
    await callback.answer()
    target = _reply_target(callback)
    if await has_answered_reminder_preferences(session, customer_id=customer.id):
        await _finish_chain(target, state, lang)
        return
    await state.set_state(AddOccasion.asking_reminder_count)
    await target.answer(
        t("prefs.ask_reminder_count", lang), reply_markup=reminder_count_keyboard(lang)
    )


async def pick_reminder_count(
    callback: CallbackQuery,
    callback_data: ReminderCountCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    """Skipping leaves the column NULL, which is how CP5 tells "not asked"
    from "chose 3"."""
    await callback.answer()
    if callback_data.value != "skip":
        await set_reminder_count(session, customer=customer, count=int(callback_data.value))
    await state.set_state(AddOccasion.asking_send_time)
    await _reply_target(callback).answer(
        t("prefs.ask_send_time", lang), reply_markup=send_time_keyboard(lang)
    )


async def pick_send_time(
    callback: CallbackQuery,
    callback_data: SendTimeCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    target = _reply_target(callback)
    if callback_data.value != "skip":
        await set_send_time(session, customer=customer, slot=callback_data.value)
        await target.answer(t("prefs.saved", lang))
    await _finish_chain(target, state, lang)


# --- renaming --------------------------------------------------------------


async def start_rename(
    callback: CallbackQuery,
    callback_data: RecipientCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    recipient = await get_recipient(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        recipient_id=callback_data.recipient_id,
    )
    await callback.answer()
    target = _reply_target(callback)
    if recipient is None:
        await target.answer(t("recipients.not_found", lang))
        return
    await state.set_state(EditRecipient.choosing_label)
    await state.update_data(recipient_id=recipient.id)
    await target.answer(
        t("recipients.choose_new_label", lang), reply_markup=label_preset_keyboard(lang)
    )


async def rename_with_preset(
    callback: CallbackQuery,
    callback_data: OccasionTypeCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    target = _reply_target(callback)
    if callback_data.type == OccasionType.CUSTOM.value:
        await state.set_state(EditRecipient.entering_label)
        await target.answer(t("occasions.enter_label", lang))
        return
    data = await state.get_data()
    recipient_id = int(data["recipient_id"])
    label = await rename_recipient(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        recipient_id=recipient_id,
        label=_type_name(lang, callback_data.type),
        type_=callback_data.type,
    )
    await state.clear()
    if label is None:
        await target.answer(t("recipients.not_found", lang))
        return
    await target.answer(t("recipients.renamed", lang, label=escape(label)))
    await _render_recipient_detail(target, session, customer, lang, recipient_id)


async def rename_with_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    raw = message.text or ""
    label = sanitize_label(raw)
    if not label:
        await message.answer(t("occasions.label_empty", lang))
        return
    if len(raw.strip()) > len(label):
        await message.answer(t("occasions.label_trimmed", lang))
    data = await state.get_data()
    recipient_id = int(data["recipient_id"])
    saved = await rename_recipient(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        recipient_id=recipient_id,
        label=label,
        type_=OccasionType.CUSTOM.value,
    )
    await state.clear()
    if saved is None:
        await message.answer(t("recipients.not_found", lang))
        return
    await message.answer(t("recipients.renamed", lang, label=escape(saved)))
    await _render_recipient_detail(message, session, customer, lang, recipient_id)


# --- per-state Back --------------------------------------------------------
# Registered once per state, never globally: a single ungated Back handler would
# shadow every one of these. The sweep enforces that.


async def back_from_type(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.clear()
    await _reply_target(callback).answer(
        t("menu.title", lang), reply_markup=main_menu_keyboard(lang)
    )


async def back_from_label(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.set_state(AddOccasion.choosing_type)
    await _reply_target(callback).answer(
        t("occasions.choose_type", lang), reply_markup=occasion_type_keyboard(lang)
    )


async def back_from_month(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.set_state(AddOccasion.choosing_type)
    await _reply_target(callback).answer(
        t("occasions.choose_type", lang), reply_markup=occasion_type_keyboard(lang)
    )


async def back_from_day(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.set_state(AddOccasion.choosing_month)
    await _reply_target(callback).answer(
        t("occasions.choose_month", lang), reply_markup=month_keyboard(lang)
    )


async def back_from_year(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    data = await state.get_data()
    await state.set_state(AddOccasion.choosing_day)
    await _reply_target(callback).answer(
        t("occasions.choose_day", lang), reply_markup=day_keyboard(lang, int(data["month"]))
    )


async def back_from_confirm(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.set_state(AddOccasion.entering_year)
    await _reply_target(callback).answer(
        t("occasions.enter_year", lang), reply_markup=year_keyboard(lang)
    )


async def back_from_rename(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    data = await state.get_data()
    recipient_id = int(data["recipient_id"])
    await state.clear()
    await _render_recipient_detail(_reply_target(callback), session, customer, lang, recipient_id)


def build_occasions_router() -> Router:
    router = Router(name="occasions")

    # Listing and detail, at state None.
    router.message.register(show_recipients, StateFilter(None), F.text.in_(OCCASIONS_LABELS))
    router.callback_query.register(
        back_to_list, StateFilter(None), RecipientListCB.filter(F.action == "back")
    )
    router.callback_query.register(
        open_recipient, StateFilter(None), RecipientCB.filter(F.action == "open")
    )
    router.callback_query.register(
        remove_recipient, StateFilter(None), RecipientCB.filter(F.action == "deactivate")
    )
    router.callback_query.register(
        remove_occasion, StateFilter(None), OccasionActionCB.filter(F.action == "deactivate")
    )
    router.callback_query.register(
        add_date_for_recipient, StateFilter(None), RecipientCB.filter(F.action == "add_date")
    )
    router.callback_query.register(edit_occasion_date, StateFilter(None), EditOccasionCB.filter())
    router.callback_query.register(
        start_rename, StateFilter(None), RecipientCB.filter(F.action == "rename")
    )
    router.callback_query.register(
        start_add, StateFilter(None), AddOccasionCB.filter(F.action == "start")
    )

    # Add flow.
    router.callback_query.register(pick_type, AddOccasion.choosing_type, OccasionTypeCB.filter())
    # catch_all: within its state this accepts ANY text, so nav and commands
    # registered ahead of it are meant to win.
    router.message.register(
        enter_label, AddOccasion.entering_label, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(pick_month, AddOccasion.choosing_month, MonthCB.filter())
    router.callback_query.register(pick_day, AddOccasion.choosing_day, DayCB.filter())
    router.message.register(
        enter_year, AddOccasion.entering_year, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(
        skip_year, AddOccasion.entering_year, YearSkipCB.filter(F.action == "skip")
    )
    router.callback_query.register(confirm_save, AddOccasion.confirming, ConfirmCB.filter())

    # The chained questions. Scope keeps the two Ha/Yo'q pairs distinguishable.
    router.callback_query.register(
        more_dates_yes,
        AddOccasion.asking_more_dates,
        YesNoCB.filter((F.scope == "dates") & (F.answer == "yes")),
    )
    router.callback_query.register(
        more_dates_no,
        AddOccasion.asking_more_dates,
        YesNoCB.filter((F.scope == "dates") & (F.answer == "no")),
    )
    router.callback_query.register(
        more_people_yes,
        AddOccasion.asking_more_people,
        YesNoCB.filter((F.scope == "people") & (F.answer == "yes")),
    )
    router.callback_query.register(
        more_people_no,
        AddOccasion.asking_more_people,
        YesNoCB.filter((F.scope == "people") & (F.answer == "no")),
    )

    # Preferences. Button-only, so no new text-waiting surface.
    router.callback_query.register(pick_flower, AddOccasion.asking_flower, FlowerCB.filter())
    router.callback_query.register(
        pick_reminder_count, AddOccasion.asking_reminder_count, ReminderCountCB.filter()
    )
    router.callback_query.register(
        pick_send_time, AddOccasion.asking_send_time, SendTimeCB.filter()
    )

    # Renaming.
    router.callback_query.register(
        rename_with_preset, EditRecipient.choosing_label, OccasionTypeCB.filter()
    )
    router.message.register(
        rename_with_text, EditRecipient.entering_label, F.text, flags={"catch_all": True}
    )

    # One Back per state.
    router.callback_query.register(back_from_type, AddOccasion.choosing_type, BackCB.filter())
    router.callback_query.register(back_from_label, AddOccasion.entering_label, BackCB.filter())
    router.callback_query.register(back_from_month, AddOccasion.choosing_month, BackCB.filter())
    router.callback_query.register(back_from_day, AddOccasion.choosing_day, BackCB.filter())
    router.callback_query.register(back_from_year, AddOccasion.entering_year, BackCB.filter())
    router.callback_query.register(back_from_confirm, AddOccasion.confirming, BackCB.filter())
    router.callback_query.register(back_from_rename, EditRecipient.choosing_label, BackCB.filter())
    return router
