"""The shadowing gate, plus a guard for the guard.

The sweep is only worth having if it can actually detect shadowing, so this
module builds deliberately broken dispatchers and asserts it catches them.
"""

from __future__ import annotations

from aiogram import Dispatcher, F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from gulbot.bot.factory import build_dispatcher
from gulbot.bot.routers import build_routers
from gulbot.bot.shadow_sweep import declared_states, render_report, sweep
from gulbot.i18n.catalog import CATALOG


def _dispatcher() -> Dispatcher:
    return build_dispatcher(session_factory=None, shop_id=0)  # type: ignore[arg-type]


async def test_production_dispatcher_has_no_shadowed_pairs() -> None:
    """The gate itself. Also runs standalone via `make shadow`."""
    violations = await sweep(_dispatcher())
    assert violations == [], render_report(violations)


async def test_sweep_enumerates_the_live_dispatcher_not_the_source() -> None:
    """Every router built by the factory must appear in the walk."""
    from gulbot.bot.shadow_sweep import walk_routers

    dispatcher = _dispatcher()
    names = {r.name for r in walk_routers(dispatcher)}
    assert {r.name for r in build_routers()} <= names


async def test_declared_states_includes_none_and_every_state() -> None:
    states = declared_states()
    assert None in states
    assert "SettingsFlow:choosing_language" in states
    assert "Onboarding:choosing_language" in states


async def test_sweep_detects_a_catch_all_registered_ahead_of_a_flow() -> None:
    """The exact regression the gate exists for: a greedy handler in front."""

    async def greedy(message: Message) -> None: ...

    dispatcher = Dispatcher()
    greedy_router = Router(name="greedy")
    greedy_router.message.register(greedy, F.text)
    dispatcher.include_router(greedy_router)
    for router in build_routers():
        dispatcher.include_router(router)

    violations = await sweep(dispatcher)
    assert violations, "sweep failed to notice a catch-all in front of every flow"
    assert any(v.kind == "DUPLICATE" for v in violations)


async def test_sweep_detects_a_catch_all_registered_first() -> None:
    """A flagged catch-all in front is CATCH_ALL_SHADOWS, not DUPLICATE."""

    async def greedy(message: Message) -> None: ...

    dispatcher = Dispatcher()
    greedy_router = Router(name="greedy")
    greedy_router.message.register(greedy, F.text, flags={"catch_all": True})
    dispatcher.include_router(greedy_router)
    for router in build_routers():
        dispatcher.include_router(router)

    violations = await sweep(dispatcher)
    assert any(v.kind == "CATCH_ALL_SHADOWS" for v in violations), render_report(violations)


async def test_sweep_detects_a_missing_state_gate() -> None:
    """An ungated text handler duplicating a state-gated one."""

    async def ungated(message: Message) -> None: ...

    dispatcher = Dispatcher()
    for router in build_routers():
        dispatcher.include_router(router)
    extra = Router(name="extra")
    extra.message.register(ungated, F.text.in_(set(CATALOG["btn.nav.back"].values())))
    dispatcher.include_router(extra)

    violations = await sweep(dispatcher)
    assert any(
        v.state == "SettingsFlow:choosing_language" and v.kind == "DUPLICATE" for v in violations
    ), render_report(violations)


async def test_a_trailing_fallback_is_not_reported() -> None:
    """Correct ordering must stay silent, or the gate becomes noise."""

    async def real(message: Message) -> None: ...

    async def catch_all(message: Message) -> None: ...

    dispatcher = Dispatcher()
    router = Router(name="ordered")
    router.message.register(real, StateFilter(None), F.text.in_({"ping"}))
    router.message.register(catch_all, F.text, flags={"catch_all": True})
    dispatcher.include_router(router)

    assert await sweep(dispatcher) == []


def test_report_is_readable_when_clean() -> None:
    assert render_report([]) == "shadow sweep: no shadowed (state, trigger) pairs"


async def test_sweep_probes_callback_queries_too() -> None:
    """The occasion flow is almost entirely inline buttons.

    If the sweep only probed messages it would be blind to that whole flow.
    """
    from gulbot.bot.shadow_sweep import probes

    kinds = {event_type for event_type, _, _ in probes()}
    assert kinds == {"message", "callback_query"}


async def test_sweep_detects_a_duplicated_callback_handler() -> None:
    """Two handlers on the same callback in the same state."""
    from aiogram.types import CallbackQuery

    from gulbot.bot.callbacks import MonthCB
    from gulbot.bot.states import AddOccasion

    async def duplicate_month(callback: CallbackQuery) -> None: ...

    dispatcher = Dispatcher()
    for router in build_routers():
        dispatcher.include_router(router)
    extra = Router(name="extra")
    extra.callback_query.register(duplicate_month, AddOccasion.choosing_month, MonthCB.filter())
    dispatcher.include_router(extra)

    violations = await sweep(dispatcher)
    assert any(
        v.kind == "DUPLICATE" and v.state == "AddOccasion:choosing_month" for v in violations
    ), render_report(violations)


async def test_a_state_scoped_catch_all_may_precede_the_global_one() -> None:
    """Otherwise every text-waiting state would be reported forever.

    `entering_label` accepts any text by design and sits ahead of the global
    fallback. That ordering is correct and must stay silent.
    """
    violations = await sweep(_dispatcher())
    assert violations == [], render_report(violations)


async def test_every_text_waiting_state_is_reachable_by_a_probe() -> None:
    """A state nobody probes is a state the gate cannot protect."""
    from gulbot.bot.shadow_sweep import declared_states

    states = {str(s) for s in declared_states()}
    assert {"AddOccasion:entering_label", "AddOccasion:entering_year"} <= states
