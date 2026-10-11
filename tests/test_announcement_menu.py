"""Concurrent updates cannot lend a staff menu to a customer/another shop."""

import asyncio

from gulbot.bot.announcement_menu import announcement_visible
from gulbot.bot.keyboards import main_menu_keyboard
from gulbot.i18n import t


async def test_menu_context_is_per_update_and_resets():
    async def render(allowed):
        token = announcement_visible.set(allowed)
        try:
            await asyncio.sleep(0)
            return {button.text for row in main_menu_keyboard("uz").keyboard for button in row}
        finally:
            announcement_visible.reset(token)

    owner, customer, other_shop = await asyncio.gather(render(True), render(False), render(False))
    label = t("btn.menu.announcement", "uz")
    assert label in owner and label not in customer and label not in other_shop
    assert not announcement_visible.get()
    assert label not in {button.text for row in main_menu_keyboard("uz").keyboard for button in row}
