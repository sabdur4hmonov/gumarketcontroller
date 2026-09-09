"""The shop acting on its own order card, in its own group.

CP13's moving parts are spread across three files that must agree with each
other, and each disagreement fails silently rather than loudly:

  * the callback PREFIX in `bot/callbacks.py` and the copy of it the chat gate
    compares against. If they drift, the buttons stop working -- the gate drops
    the tap before any handler sees it, so there is no error anywhere, just a
    button that does nothing.
  * the FSM state the gate lets a typed rejection reason through on. If that
    drifts, the admin types a reason into the group and the bot ignores it.

Neither is the kind of bug a test of the happy path would catch, because both
look exactly like "nothing happened".
"""

from __future__ import annotations

from gulbot.bot.callbacks import OrderAdminCB
from gulbot.bot.middlewares import ADMIN_CALLBACK_PREFIX
from gulbot.bot.states import AdminOrder


def test_the_gate_and_the_buttons_agree_on_the_prefix() -> None:
    """The one string a group is allowed to send.

    Compared against the factory's OWN prefix rather than a second literal,
    so renaming the factory fails the build instead of quietly disarming the
    buttons.
    """
    assert OrderAdminCB.__prefix__ == ADMIN_CALLBACK_PREFIX


def test_every_button_the_card_carries_passes_the_gate() -> None:
    """Not just the prefix in the abstract -- the actual packed payloads."""
    for payload in OrderAdminCB.samples():
        assert payload.startswith(f"{ADMIN_CALLBACK_PREFIX}:"), payload


def test_the_card_offers_exactly_confirm_and_reject() -> None:
    """A third action would be a status transition nobody reviewed."""
    actions = {OrderAdminCB.unpack(p).action for p in OrderAdminCB.samples()}
    assert actions == {"confirm", "reject"}


def test_the_reject_reason_state_exists_for_the_gate_to_name() -> None:
    """The gate imports this state to decide whether a group MESSAGE gets
    through. Renaming it there and not here would reopen the group bug for
    text, which is the half that privacy mode used to hide."""
    assert AdminOrder.entering_reject_reason.state == "AdminOrder:entering_reject_reason"
