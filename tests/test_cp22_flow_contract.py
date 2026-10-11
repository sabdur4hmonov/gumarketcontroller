"""The announcement feature must be reachable in the real shop dispatcher."""

from gulbot.bot.routers import build_routers


def test_staff_authoring_router_is_part_of_shop_bot():
    assert "announcements" in {router.name for router in build_routers()}
