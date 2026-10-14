"""RAM only: every five minutes, two consecutive highs, at most six hours."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .resources import available_mib

ROOT = Path(__file__).resolve().parents[2]


def wait_for_ram(
    read: Callable[[], float],
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    log: Callable[[dict[str, Any]], None],
    *,
    budget: float = 21600,
) -> bool:
    deadline = clock() + budget
    streak = 0
    while True:
        free = read()
        streak = streak + 1 if free >= 3072 else 0
        log({"at": datetime.now(UTC).isoformat(), "free_mib": round(free, 2), "streak": streak})
        if streak >= 2:
            return True
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        sleep(min(300, remaining))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    target = args.state.resolve()
    if not target.is_relative_to(ROOT / ".cp22-stage/cp25"):
        raise SystemExit("RAM monitor state must stay in owned staging")
    if target.exists():
        raise SystemExit("Refuse to restart/extend an existing six-hour wait")
    target.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
        "interval_s": 300,
        "maximum_wait_s": 21600,
        "threshold_mib": 3072,
        "phase": "waiting_ram",
        "readings": [],
    }

    def save() -> None:
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)

    def log(reading: dict[str, Any]) -> None:
        state["readings"].append(reading)
        save()
        with (ROOT / "docs/CP25_STATUS.md").open("a", encoding="utf-8") as stream:
            stream.write(
                f"\n{reading['at']} — overnight RAM {reading['free_mib']}MiB, "
                f"consecutive >=3072 readings {reading['streak']}/2.\n"
            )

    state["phase"] = (
        "ready" if wait_for_ram(available_mib, time.monotonic, time.sleep, log) else "expired"
    )
    state["finished_at"] = datetime.now(UTC).isoformat()
    save()
    with (ROOT / "docs/CP25_STATUS.md").open("a", encoding="utf-8") as stream:
        stream.write(
            f"\n{state['finished_at']} — bounded RAM wait {state['phase']}; no guard lowered.\n"
        )


if __name__ == "__main__":
    main()
