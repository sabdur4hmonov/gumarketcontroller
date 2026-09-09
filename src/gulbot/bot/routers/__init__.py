"""Router registration order is load-bearing.

nav comes first so Back and Cancel always win; the fallback comes last so it can
only catch what nothing else wanted. The shadow sweep enforces this against the
LIVE dispatcher and fails the build if it is violated.

These are factories rather than module-level singletons: an aiogram Router can
only ever be attached to one Dispatcher, so singletons make a second dispatcher
(in tests, or in the sweep) impossible to build.
"""

from aiogram import Router

from gulbot.bot.routers.admin_orders import build_admin_orders_router
from gulbot.bot.routers.browse import build_browse_router
from gulbot.bot.routers.fallback import build_fallback_router
from gulbot.bot.routers.menu import build_menu_router
from gulbot.bot.routers.nav import build_nav_router
from gulbot.bot.routers.occasions import build_occasions_router
from gulbot.bot.routers.onboarding import build_onboarding_router
from gulbot.bot.routers.orders import build_orders_router
from gulbot.bot.routers.phone import build_phone_router
from gulbot.bot.routers.settings import build_settings_router


def build_routers() -> tuple[Router, ...]:
    """Order matters. Do not sort this."""
    return (
        build_nav_router(),
        build_onboarding_router(),
        # CP13. The only router here that serves a group, and it goes after BOTH
        # escape hatches: Cancel lives in nav, /start lives in onboarding, and
        # the standing rule since CP2 is that those two win from every state.
        # `enter_reason` accepts any text, so anywhere earlier it shadows them.
        #
        # The first draft put it first and the shadow sweep failed the build,
        # correctly, naming both. Moving it after nav fixed Cancel and left
        # /start still shadowed -- which is exactly the value of a gate that
        # walks the live dispatcher rather than a rule someone remembers.
        #
        # This ordering is only safe because the chat gate refuses commands and
        # button labels as rejection reasons, so nav and onboarding are never
        # actually reached FROM a group -- the static rule and the runtime
        # behaviour agree rather than trading off. Cancel comes back as an
        # inline button on the prompt, which arrives by callback prefix and
        # touches neither router.
        build_admin_orders_router(),
        build_settings_router(),
        build_occasions_router(),
        # CP10c. Owns ONE state (Onboarding.sharing_phone) and nothing else, so
        # its position here is not delicate -- but it goes after occasions
        # because that is the flow which hands control to it.
        build_phone_router(),
        # CP11. Owns two button-only states and the menu entry. It sits
        # ahead of orders because it hands control to it: a bouquet chosen
        # here starts the order flow through the SAME callback a reminder
        # carries, rather than a second entry point that could drift.
        build_browse_router(),
        # CP10. Its own callback prefixes and its own states, so it neither
        # shadows nor is shadowed by the occasions flow.
        build_orders_router(),
        build_menu_router(),
        build_fallback_router(),
    )


__all__ = ["build_routers"]
