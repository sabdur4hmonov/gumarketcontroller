"""The occurrence engine must stay pure.

"If a test needs a database, the boundary is in the wrong place." These tests
enforce that mechanically, so the boundary cannot erode one convenient import
at a time.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Anything that reaches the network, the disk, a database or Telegram.
FORBIDDEN_MODULES = (
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "aiogram",
    "redis",
    "celery",
    "alembic",
)

PURE_MODULES = ("gulbot.scheduling.occurrences",)


def test_engine_imports_nothing_impure() -> None:
    """Checked in a FRESH interpreter, so transitive imports count too.

    Importing the module inside this process would prove nothing: pytest has
    already imported sqlalchemy for the other suites.
    """
    program = (
        "import sys\n"
        f"import {PURE_MODULES[0]}\n"
        f"forbidden = {FORBIDDEN_MODULES!r}\n"
        "found = sorted(m for m in forbidden if m in sys.modules)\n"
        "print(','.join(found))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    leaked = result.stdout.strip()
    assert leaked == "", f"the pure engine pulled in: {leaked}"


def test_engine_does_not_read_the_environment() -> None:
    """No settings, no .env, no clock. `now` is always passed in."""
    source = (REPO_ROOT / "src/gulbot/scheduling/occurrences.py").read_text(encoding="utf-8")
    for forbidden in ("get_settings", "os.environ", "datetime.now(", "date.today("):
        assert forbidden not in source, f"engine reaches outside itself: {forbidden}"


def test_pure_test_modules_use_no_database_fixture() -> None:
    """These suites must not acquire the db fixture, directly or via a mark."""
    for name in ("test_occurrence_engine.py", "test_clustering.py"):
        source = (REPO_ROOT / "tests" / name).read_text(encoding="utf-8")
        assert "db: AsyncConnection" not in source, name
        assert "pytest.mark.infra" not in source, name
        assert "shop_id" not in source, name


def test_engine_is_deterministic_across_processes() -> None:
    """Same inputs, separate interpreter, identical output."""
    program = (
        "from datetime import datetime, UTC\n"
        "from gulbot.scheduling.occurrences import OccasionSpec, plan_notifications\n"
        "rows = plan_notifications(\n"
        "    [OccasionSpec(1, month=3, day=8), OccasionSpec(2, month=3, day=9)],\n"
        "    now_utc=datetime(2027, 2, 20, 3, tzinfo=UTC),\n"
        ")\n"
        "print('|'.join(f'{r.unique_key}@{r.due_at_utc.isoformat()}' for r in rows))\n"
    )
    runs = {
        subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=True,
        ).stdout.strip()
        for _ in range(2)
    }
    assert len(runs) == 1, "engine output differs between runs"
    assert next(iter(runs)), "engine produced nothing"
