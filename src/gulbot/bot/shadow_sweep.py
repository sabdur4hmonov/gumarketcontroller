"""Handler-shadowing sweep.

Handler shadowing is a REGISTRATION-ORDER bug: aiogram dispatches to the first
handler whose filters pass, so a handler registered earlier can make a later one
unreachable. Ordering exists only at registration time, which is why this sweep
walks the LIVE dispatcher after every router has been included. A static scan of
the source files cannot see registration order and would not catch the bug.

Method: synthesise a probe for every (state, trigger) pair the bot can actually
receive -- every button label in every language, plus free text and /start, in
every declared FSM state and at state None -- then evaluate the real filter
chain of every registered handler against it, in registration order.

Some handlers are catch-alls BY DESIGN: the global unknown-text fallback, and
any state that waits for free text (a label, a year) and must accept whatever
arrives. Those declare `flags={"catch_all": True}`. A catch-all is allowed to be
shadowed, and is allowed to shadow another catch-all -- a state-scoped one
legitimately sits in front of the global one.

Two cases are reported:

  DUPLICATE          two or more specific (non-catch-all) handlers match the
                     same probe, so the later ones are unreachable.
  CATCH_ALL_SHADOWS  a catch-all is registered BEFORE a specific handler and
                     swallows input meant for it. This is the registration-order
                     bug proper.

A catch-all matching AFTER the specific handler is correct and is not reported.
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from aiogram import Dispatcher, Router
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Chat, Message, TelegramObject, User

from gulbot.bot import states as states_module
from gulbot.bot.callbacks import all_callback_samples
from gulbot.i18n.translator import button_labels

PROBE_USER = User(id=424242, is_bot=False, first_name="Probe")
PROBE_CHAT = Chat(id=424242, type="private")

# Text that matches no button, standing in for a customer typing an address or
# a stray word. This is what a careless catch-all handler will swallow.
FREE_TEXT = "istalgan matn 123"


@dataclass(frozen=True)
class HandlerId:
    router: str
    name: str
    location: str
    is_catch_all: bool

    def __str__(self) -> str:
        tag = " [catch-all]" if self.is_catch_all else ""
        return f"{self.router}.{self.name}{tag} ({self.location})"


@dataclass(frozen=True)
class Violation:
    kind: str
    state: str
    trigger: str
    handlers: tuple[HandlerId, ...]

    def render(self) -> str:
        lines = [
            f"  {self.kind}: state={self.state} trigger={self.trigger!r}",
            *(f"      {h}" for h in self.handlers),
        ]
        return "\n".join(lines)


def declared_states() -> list[str | None]:
    """None plus every State declared in gulbot.bot.states."""
    found: list[str | None] = [None]
    for _, obj in inspect.getmembers(states_module, inspect.isclass):
        if issubclass(obj, StatesGroup) and obj is not StatesGroup:
            for member in obj.__all_states__:
                assert isinstance(member, State)
                found.append(member.state)
    return found


def walk_routers(router: Router) -> list[Router]:
    """Routers in dispatch order: the router itself, then its children in order."""
    ordered = [router]
    for sub in router.sub_routers:
        ordered.extend(walk_routers(sub))
    return ordered


def _location(callback: object) -> str:
    try:
        source_file = inspect.getsourcefile(callback)  # type: ignore[arg-type]
        _, line = inspect.getsourcelines(callback)  # type: ignore[arg-type]
    except (TypeError, OSError):
        return "<unknown>"
    if source_file is None:
        return "<unknown>"
    tail = source_file.rsplit("gulbot", 1)[-1].lstrip("\\/")
    return f"{tail}:{line}"


async def _filters_pass(filters: object, event: TelegramObject, raw_state: str | None) -> bool:
    """Evaluate a filter chain exactly the way the dispatcher would."""
    if not filters:
        return True
    kwargs = {
        "raw_state": raw_state,
        "event_from_user": PROBE_USER,
        "event_chat": PROBE_CHAT,
        "bot": None,
    }
    for flt in filters:  # type: ignore[attr-defined]
        try:
            result = await flt.call(event, **kwargs)
        except Exception:
            # A filter that cannot run against a synthetic event tells us
            # nothing; treat it as non-matching rather than crashing the gate.
            return False
        if not result:
            return False
    return True


def make_message(text: str) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(tz=UTC),
        chat=PROBE_CHAT,
        from_user=PROBE_USER,
        text=text,
    )


def make_callback(data: str) -> CallbackQuery:
    return CallbackQuery(
        id="probe",
        from_user=PROBE_USER,
        chat_instance="probe",
        data=data,
        message=make_message("carrier"),
    )


async def matching_handlers(
    dispatcher: Dispatcher, event: TelegramObject, raw_state: str | None, event_type: str
) -> list[HandlerId]:
    matched: list[HandlerId] = []
    for router in walk_routers(dispatcher):
        observer = router.observers.get(event_type)
        if observer is None:
            continue
        # Router-scope filters (router.message.filter(...)) gate every handler
        # in that router; aiogram keeps them on the observer's own handler.
        router_filters = getattr(observer._handler, "filters", None)  # noqa: SLF001
        if not await _filters_pass(router_filters, event, raw_state):
            continue
        for handler in observer.handlers:
            if await _filters_pass(handler.filters, event, raw_state):
                matched.append(
                    HandlerId(
                        router=router.name,
                        name=getattr(handler.callback, "__name__", repr(handler.callback)),
                        location=_location(handler.callback),
                        is_catch_all=bool(handler.flags.get("catch_all", False)),
                    )
                )
    return matched


def probes() -> list[tuple[str, str, TelegramObject]]:
    """(event_type, trigger, event) for everything the bot can receive.

    Message triggers come from the i18n catalog, so a new button is covered the
    moment it is added. Callback triggers come from each CallbackData factory's
    samples(), so a new inline factory is covered the moment it is defined.
    Neither list has to be maintained by hand.
    """
    items: list[tuple[str, str, TelegramObject]] = [
        ("message", trigger, make_message(trigger))
        for trigger in sorted(button_labels()) + [FREE_TEXT, "/start"]
    ]
    items += [
        ("callback_query", data, make_callback(data)) for data in sorted(all_callback_samples())
    ]
    return items


async def sweep(dispatcher: Dispatcher) -> list[Violation]:
    violations: list[Violation] = []
    all_probes = probes()

    for raw_state in declared_states():
        for event_type, trigger, event in all_probes:
            matched = await matching_handlers(dispatcher, event, raw_state, event_type)
            if len(matched) < 2:
                continue

            specific = [h for h in matched if not h.is_catch_all]
            if len(specific) > 1:
                violations.append(Violation("DUPLICATE", str(raw_state), trigger, tuple(specific)))
                continue

            # A catch-all standing in front of a specific handler eats input
            # meant for it. A catch-all in front of another catch-all is fine:
            # a state-scoped one legitimately precedes the global fallback.
            first_catch_all = next((i for i, h in enumerate(matched) if h.is_catch_all), None)
            if first_catch_all is None:
                continue
            if any(not h.is_catch_all for h in matched[first_catch_all + 1 :]):
                violations.append(
                    Violation("CATCH_ALL_SHADOWS", str(raw_state), trigger, tuple(matched))
                )
    return violations


def render_report(violations: list[Violation]) -> str:
    if not violations:
        return "shadow sweep: no shadowed (state, trigger) pairs"
    body = "\n".join(v.render() for v in violations)
    return f"shadow sweep: {len(violations)} shadowed (state, trigger) pair(s)\n{body}"


async def run() -> int:
    from gulbot.bot.factory import build_dispatcher

    # The sweep only evaluates filters, so no database is touched; the factory
    # still builds the dispatcher exactly as production does, including the
    # router registration order that is the whole point.
    dispatcher = build_dispatcher(session_factory=None, shop_id=0)  # type: ignore[arg-type]
    violations = await sweep(dispatcher)
    print(render_report(violations))
    return 1 if violations else 0


def main() -> None:
    import asyncio

    # Button labels contain emoji and Cyrillic; the Windows console is cp1251.
    # Without this the gate dies on its own report instead of reporting.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
