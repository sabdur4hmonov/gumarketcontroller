"""Inline callback data factories.

Each factory exposes `samples()`, and the shadow sweep probes the live
dispatcher with every sample. Adding a factory therefore extends the gate
automatically -- there is no separate list to keep in sync.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData

from gulbot.models.occasion import MAX_DAY_IN_MONTH, OccasionType


class OccasionTypeCB(CallbackData, prefix="occtype"):
    type: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(type=t.value).pack() for t in OccasionType]


class MonthCB(CallbackData, prefix="occmonth"):
    month: int

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(month=m).pack() for m in range(1, 13)]


class DayCB(CallbackData, prefix="occday"):
    day: int

    @classmethod
    def samples(cls) -> list[str]:
        # First, last and a Feb-29 boundary value.
        return [cls(day=d).pack() for d in (1, 15, 29, 30, max(MAX_DAY_IN_MONTH))]


class YearSkipCB(CallbackData, prefix="occyear"):
    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="skip").pack()]


class ConfirmCB(CallbackData, prefix="occconfirm"):
    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action=a).pack() for a in ("save", "discard")]


class BackCB(CallbackData, prefix="occback"):
    """Back inside the inline flow. Handled per state, never globally."""

    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="back").pack()]


class OccasionActionCB(CallbackData, prefix="occact"):
    action: str
    occasion_id: int

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="deactivate", occasion_id=1).pack()]


class AddOccasionCB(CallbackData, prefix="occadd"):
    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="start").pack()]


class YesNoCB(CallbackData, prefix="occyn"):
    """Answers to the chained "yana ...?" questions.

    `scope` distinguishes the two loops so the same Ha/Yo'q pair can appear
    twice without the handlers becoming ambiguous.
    """

    scope: str
    answer: str

    @classmethod
    def samples(cls) -> list[str]:
        return [
            cls(scope=scope, answer=answer).pack()
            for scope in ("dates", "people")
            for answer in ("yes", "no")
        ]


class RecipientCB(CallbackData, prefix="rcp"):
    action: str
    recipient_id: int

    @classmethod
    def samples(cls) -> list[str]:
        return [
            cls(action=action, recipient_id=1).pack()
            for action in ("open", "rename", "deactivate", "add_date")
        ]


class EditOccasionCB(CallbackData, prefix="occedit"):
    occasion_id: int

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(occasion_id=1).pack()]


class RecipientListCB(CallbackData, prefix="rcplist"):
    action: str

    @classmethod
    def samples(cls) -> list[str]:
        return [cls(action="back").pack()]


ALL_FACTORIES: tuple[type[CallbackData], ...] = (
    OccasionTypeCB,
    MonthCB,
    DayCB,
    YearSkipCB,
    ConfirmCB,
    BackCB,
    OccasionActionCB,
    AddOccasionCB,
    YesNoCB,
    RecipientCB,
    EditOccasionCB,
    RecipientListCB,
)


def all_callback_samples() -> list[str]:
    samples: list[str] = []
    for factory in ALL_FACTORIES:
        samples.extend(factory.samples())  # type: ignore[attr-defined]
    return samples
