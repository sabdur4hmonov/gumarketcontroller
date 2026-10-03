"""PASS 5 fixes that are configuration: task time limits, beat expiry, log rotation.

Configuration tests prove the values are WIRED where the runtime reads them --
`app.tasks[...]` is what the worker consults, `beat_schedule[...]["options"]` is
what beat passes to `apply_async`, the compose file is what Docker reads. That
the runtime then ENFORCES them was shown live, not here, because two of the three
cannot be enforced inside this suite: Celery's time limits only work in the
prefork pool (the Windows solo pool ignores them), and log rotation only applies
to a recreated container. See docs/DEPLOY.md for both.
"""

from __future__ import annotations

from pathlib import Path

import yaml

import gulbot.worker.tasks  # noqa: F401  -- registers the tasks on the app
from gulbot.bot.factory import TELEGRAM_REQUEST_TIMEOUT
from gulbot.sending.transport import BREAKER_THRESHOLD
from gulbot.worker.app import TICK_SOFT_LIMIT, app

REPO_ROOT = Path(__file__).resolve().parents[1]

GULBOT_TASKS = {
    "gulbot.send_due_reminders",
    "gulbot.send_order_pings",
    "gulbot.check_health",
    "gulbot.send_daily_summary",
    "gulbot.materialize_all_shops",
    "gulbot.finalize_album",
    "gulbot.notify_page_answer",
    "gulbot.scrub_expired_pages",
}


def test_every_task_has_a_soft_and_a_hard_time_limit() -> None:
    """DEFECT IF THIS FAILS. Before pass 5 no task had a limit, so one hung
    statement or send held the worker -- which runs one task at a time -- forever.
    A new task added without limits fails the first assertion."""
    registered = {name for name in app.tasks if name.startswith("gulbot.")}
    assert registered == GULBOT_TASKS, "a task was added or renamed; give it limits here"
    for name in sorted(GULBOT_TASKS):
        task = app.tasks[name]
        assert task.soft_time_limit, f"{name} has no soft_time_limit"
        assert task.time_limit, f"{name} has no time_limit"
        assert task.soft_time_limit < task.time_limit, f"{name}: soft must fire before hard"


def test_a_tick_limit_leaves_room_for_the_worst_outage_tick() -> None:
    """The limit is a backstop for what nothing else bounds. It must not cut off
    a tick that the circuit breaker is already ending on its own."""
    outage_tick = BREAKER_THRESHOLD * TELEGRAM_REQUEST_TIMEOUT
    assert 4 * outage_tick <= TICK_SOFT_LIMIT


def test_periodic_ticks_expire_before_the_next_one_is_due() -> None:
    """DEFECT IF THIS FAILS. A tick that has not started by the time the next is
    enqueued is superseded by it; without an expiry a worker stuck behind a long
    task comes back to a queue of stale ticks and runs every one."""
    for entry_name in ("send-due-reminders", "send-order-pings", "health-check"):
        entry = app.conf.beat_schedule[entry_name]
        expires = entry.get("options", {}).get("expires")
        assert expires is not None, f"{entry_name} has no expires"
        assert 0 < expires < entry["schedule"], f"{entry_name}: expires {expires}"


def test_every_container_rotates_its_logs() -> None:
    """DEFECT IF THIS FAILS. Docker's default json-file driver never rotates."""
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, service in compose["services"].items():
        logging = service.get("logging", {})
        options = logging.get("options", {})
        assert logging.get("driver") == "json-file", f"{name}: no logging driver"
        assert options.get("max-size"), f"{name}: no max-size"
        assert options.get("max-file"), f"{name}: no max-file"
