"""FSM states.

Every text-waiting handler must be gated on one of these. A handler that waits
for free text at state None will swallow input intended for a flow, which is the
failure mode the shadowing sweep exists to catch.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    choosing_language = State()


class SettingsFlow(StatesGroup):
    choosing_language = State()
