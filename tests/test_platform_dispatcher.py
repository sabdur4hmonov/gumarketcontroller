"""The platform bot obeys the same two gates as the customer bot.

1. THE SHADOW SWEEP. No handler in the onboarding conversation may make
   another unreachable -- the build gate, now run against the platform
   dispatcher as well (`python -m gulbot.bot.shadow_sweep` sweeps both).
2. CANCEL AND /START WIN FROM EVERY STATE. The standing rule since CP2. In the
   owner's conversation /start means "pick up where I left off" rather than
   "start over", but it must still be reachable from every step, including the
   ones that wait for free text.
"""

from __future__ import annotations

import pytest
from aiogram import Dispatcher

from gulbot.bot.factory import build_platform_dispatcher
from gulbot.bot.shadow_sweep import make_message, matching_handlers, sweep
from gulbot.bot.states import ShopOnboarding
from gulbot.i18n.catalog import CATALOG

OWNER_STATES = [state.state for state in ShopOnboarding.__all_states__]


def _platform() -> Dispatcher:
    return build_platform_dispatcher(session_factory=None)  # type: ignore[arg-type]


async def test_the_platform_dispatcher_has_no_shadowed_handlers() -> None:
    assert await sweep(_platform()) == []


def test_the_gate_sweeps_the_platform_dispatcher_too() -> None:
    import inspect

    from gulbot.bot import shadow_sweep

    assert "build_platform_dispatcher" in inspect.getsource(shadow_sweep.run)


@pytest.mark.parametrize("cancel_label", sorted(set(CATALOG["btn.nav.cancel"].values())))
async def test_cancel_is_the_first_match_in_every_owner_state(cancel_label: str) -> None:
    dispatcher = _platform()
    for state in [None, *OWNER_STATES]:
        matched = await matching_handlers(dispatcher, make_message(cancel_label), state, "message")
        assert matched, f"nothing handles Cancel in {state}"
        assert matched[0].name == "cancel_onboarding", (state, matched)


async def test_start_is_the_first_match_in_every_owner_state() -> None:
    dispatcher = _platform()
    for state in [None, *OWNER_STATES]:
        matched = await matching_handlers(dispatcher, make_message("/start"), state, "message")
        assert matched and matched[0].name == "start_or_resume", (state, matched)


async def test_every_owner_state_has_a_handler_for_free_text() -> None:
    """No step silently ignores the owner: whatever they type is either the
    answer or earns a re-prompt."""
    dispatcher = _platform()
    for state in OWNER_STATES:
        matched = await matching_handlers(
            dispatcher, make_message("istalgan matn 123"), state, "message"
        )
        assert matched, f"free text in {state} reaches nothing"
