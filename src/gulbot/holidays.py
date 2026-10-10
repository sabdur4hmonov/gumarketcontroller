"""The holidays a shop can run a campaign for (CP20).

A FIXED LIST, chosen by the owner: five with a fixed date, and two lunar
holidays whose date moves every year. A lunar holiday is reminded only in a
year for which the platform admin has entered its date in /admin
(`holiday_dates`); nothing here guesses one.

THE PLANNER SEES A HOLIDAY AS ONE MORE DATE. Each holiday has a stable
NEGATIVE `spec_id` that stands in for an occasion id inside the pure occurrence
engine (scheduling/occurrences.py), so clustering, the merge window and the
weekly cap treat a holiday exactly like a personal date -- one rule for both,
not two. Real occasion ids are positive, so the two can never collide. The
materializer turns a negative id back into `scheduled_notifications.holiday`.

The spec ids are part of every holiday row's merge_key, which is part of the
ledger key in message_log: never renumber one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Holiday:
    key: str
    #: Stands in for an occasion id in the planner. Negative; never reused.
    spec_id: int
    #: The fixed date, or None for a lunar holiday (its date is per year).
    month: int | None = None
    day: int | None = None

    @property
    def lunar(self) -> bool:
        return self.month is None


HOLIDAYS: Final[tuple[Holiday, ...]] = (
    Holiday("valentines", -101, 2, 14),
    Holiday("womens_day", -102, 3, 8),
    Holiday("navruz", -103, 3, 21),
    Holiday("teachers_day", -104, 10, 1),
    # The evening flowers are bought for, not 1 January.
    Holiday("new_year", -105, 12, 31),
    Holiday("ramazon_hayit", -106),
    Holiday("qurbon_hayit", -107),
)

BY_KEY: Final[dict[str, Holiday]] = {h.key: h for h in HOLIDAYS}
BY_SPEC_ID: Final[dict[int, Holiday]] = {h.spec_id: h for h in HOLIDAYS}
LUNAR_KEYS: Final[tuple[str, ...]] = tuple(h.key for h in HOLIDAYS if h.lunar)

#: For CHECK constraints: every key, and the lunar ones.
HOLIDAY_KEYS_SQL: Final = ", ".join(f"'{h.key}'" for h in HOLIDAYS)
LUNAR_KEYS_SQL: Final = ", ".join(f"'{key}'" for key in LUNAR_KEYS)
#: Longest key; the columns are sized from it.
KEY_LENGTH: Final = 24


def is_holiday_spec(spec_id: int) -> bool:
    return spec_id < 0
