"""Router registration order is load-bearing.

nav comes first so Back and Cancel always win; the fallback comes last so it can
only catch what nothing else wanted. The shadow sweep enforces this against the
LIVE dispatcher and fails the build if it is violated.

These are factories rather than module-level singletons: an aiogram Router can
only ever be attached to one Dispatcher, so singletons make a second dispatcher
(in tests, or in the sweep) impossible to build.
"""

from aiogram import Router

from gulbot.bot.routers.fallback import build_fallback_router
from gulbot.bot.routers.menu import build_menu_router
from gulbot.bot.routers.nav import build_nav_router
from gulbot.bot.routers.occasions import build_occasions_router
from gulbot.bot.routers.onboarding import build_onboarding_router
from gulbot.bot.routers.settings import build_settings_router


def build_routers() -> tuple[Router, ...]:
    """Order matters. Do not sort this."""
    return (
        build_nav_router(),
        build_onboarding_router(),
        build_settings_router(),
        build_occasions_router(),
        build_menu_router(),
        build_fallback_router(),
    )


__all__ = ["build_routers"]
