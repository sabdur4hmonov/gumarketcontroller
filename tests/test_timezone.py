"""Asia/Tashkent must resolve, and must resolve to UTC+5 all year.

CP4's entire occurrence engine sits on this. Windows ships no IANA tz database,
so the `tzdata` package is what makes ZoneInfo work here -- and it must be a
DIRECT dependency: it currently also arrives transitively via kombu/psycopg/
tzlocal, which would let a future dependency change break the scheduler silently.
"""

from __future__ import annotations

import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gulbot.config import TASHKENT

REPO_ROOT = Path(__file__).resolve().parents[1]
UTC_PLUS_5 = timedelta(hours=5)


def test_zone_resolves() -> None:
    assert ZoneInfo("Asia/Tashkent") == TASHKENT


@pytest.mark.parametrize("month", range(1, 13))
def test_offset_is_utc_plus_5_every_month(month: int) -> None:
    """Uzbekistan has no DST. Any month showing +6 means a bad tz database."""
    moment = datetime(2026, month, 15, 12, 0, tzinfo=TASHKENT)
    assert moment.utcoffset() == UTC_PLUS_5


def test_offset_is_stable_across_european_dst_switches() -> None:
    """The dates where a naive +offset assumption would drift."""
    for moment in (
        datetime(2026, 3, 29, 3, 30, tzinfo=TASHKENT),
        datetime(2026, 10, 25, 3, 30, tzinfo=TASHKENT),
    ):
        assert moment.utcoffset() == UTC_PLUS_5


def test_tzdata_is_a_direct_dependency() -> None:
    """Not merely importable -- pinned, so a dependency change cannot drop it."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    assert any(d.startswith("tzdata") for d in deps), deps
