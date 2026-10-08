"""/admin in the PLATFORM bot: a one-time login link for the admin panel (CP18).

Only for a Telegram id in PLATFORM_ADMIN_TELEGRAM_IDS. For anyone else the
filter does not match, so "/admin" falls through to onboarding exactly as it
did before this router existed -- the platform bot says nothing about a panel
to someone who cannot use it.

The link is sent with the link preview OFF, and opening it only shows a
button: a preview fetch must never be what spends it (see gulbot.web.admin).
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, Filter
from aiogram.types import LinkPreviewOptions, Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.i18n import t
from gulbot.services import admin_auth
from gulbot.web.links import base_url, pages_available


class IsPlatformAdmin(Filter):
    async def __call__(self, message: Message) -> bool:
        user = message.from_user
        return user is not None and user.id in admin_auth.admin_ids()


async def send_login_link(message: Message, session: AsyncSession, lang: str) -> None:
    user = message.from_user
    assert user is not None  # the filter checked
    if not pages_available():
        # Production without HTTPS: a Secure session cookie could not be set,
        # and an http:// admin link must never be sent.
        await message.answer(t("admin.unavailable", lang))
        return
    raw = await admin_auth.mint_login_link(
        session, telegram_id=user.id, allowed=admin_auth.admin_ids()
    )
    if raw is None:
        await message.answer(t("admin.link_refused", lang))
        return
    minutes = int(admin_auth.LINK_TTL.total_seconds() // 60)
    await message.answer(
        t("admin.link", lang, url=f"{base_url()}/admin/login/{raw}", minutes=minutes),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def build_platform_admin_router() -> Router:
    router = Router(name="platform_admin")
    router.message.register(send_login_link, Command("admin"), IsPlatformAdmin())
    return router
