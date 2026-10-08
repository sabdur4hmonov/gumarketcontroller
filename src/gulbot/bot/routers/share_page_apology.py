"""Making an Uzrnoma -- an apology letter (CP17).

Steps, each a picker except the letter itself: the page's language, the
letter (the customer's own words, up to MESSAGE_MAX), the design, whether to
be told when it is forgiven, then the summary -- whose "Yaratish" goes
through the shared confirm handler in share_pages.py, so creation limits,
tokens and the link message are the same for every kind of page.
"""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from gulbot.bot.callbacks import PageChoiceCB, PageLangCB, PageTemplateCB
from gulbot.bot.keyboards_pages import confirm_keyboard, toggle_keyboard
from gulbot.bot.routers.share_pages import LANG_NAMES, _ask_template, _take_text, _target
from gulbot.bot.states import ApologyPage
from gulbot.i18n import t
from gulbot.models.share_page import MESSAGE_MAX, PAGE_LANGUAGES, PAGE_TEMPLATES
from gulbot.utils.render import escape
from gulbot.web.render import THEME_NAMES

#: How much of the letter the summary quotes back.
SUMMARY_QUOTE = 200


async def start_apology(target: Message, state: FSMContext, lang: str) -> None:
    from gulbot.bot.keyboards_pages import page_lang_keyboard
    from gulbot.models.share_page import PageKind

    await state.update_data(kind=PageKind.APOLOGY.value)
    await state.set_state(ApologyPage.choosing_lang)
    await target.answer(t("pages.choose_lang", lang), reply_markup=page_lang_keyboard())


async def apology_lang(
    callback: CallbackQuery, callback_data: PageLangCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.lang not in PAGE_LANGUAGES:
        return
    await state.update_data(page_lang=callback_data.lang)
    await state.set_state(ApologyPage.entering_text)
    await _target(callback).answer(t("pages.ask_apology", lang, max=MESSAGE_MAX))


async def apology_text(message: Message, state: FSMContext, lang: str) -> None:
    text = await _take_text(message, lang, MESSAGE_MAX, multiline=True)
    if text is None:
        return
    await state.update_data(letter=text)
    await _ask_template(message, state, lang, ApologyPage.choosing_template, "apology")


async def apology_template(
    callback: CallbackQuery, callback_data: PageTemplateCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.template not in PAGE_TEMPLATES:
        return
    await state.update_data(template=callback_data.template)
    await state.set_state(ApologyPage.choosing_notify)
    await _target(callback).answer(
        t("pages.ask_notify_apology", lang), reply_markup=toggle_keyboard(lang, "notify")
    )


def apology_ready(data: dict[str, Any]) -> bool:
    return (
        data.get("page_lang") in PAGE_LANGUAGES
        and isinstance(data.get("letter"), str)
        and data.get("template") in PAGE_TEMPLATES
        and isinstance(data.get("notify"), bool)
    )


async def apology_notify(
    callback: CallbackQuery, callback_data: PageChoiceCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.field != "notify" or callback_data.value not in ("yes", "no"):
        return
    await state.update_data(notify=callback_data.value == "yes")
    data = await state.get_data()
    if not apology_ready(data):
        await state.clear()
        await _target(callback).answer(t("pages.cancelled", lang))
        return
    letter = data["letter"]
    quote = letter if len(letter) <= SUMMARY_QUOTE else letter[: SUMMARY_QUOTE - 1] + "…"
    await state.set_state(ApologyPage.confirming)
    await _target(callback).answer(
        t(
            "pages.confirm_apology",
            lang,
            letter=escape(quote),
            lang_name=LANG_NAMES[data["page_lang"]],
            template=THEME_NAMES[data["template"]],
            notify=t("pages.word_yes" if data["notify"] else "pages.word_no", lang),
        ),
        reply_markup=confirm_keyboard(lang),
    )


def build_share_page_apology_router() -> Router:
    router = Router(name="share_page_apology")
    router.callback_query.register(apology_lang, ApologyPage.choosing_lang, PageLangCB.filter())
    router.message.register(
        apology_text, ApologyPage.entering_text, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(
        apology_template, ApologyPage.choosing_template, PageTemplateCB.filter()
    )
    router.callback_query.register(
        apology_notify, ApologyPage.choosing_notify, PageChoiceCB.filter()
    )
    return router
