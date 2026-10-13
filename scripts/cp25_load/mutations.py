"""Prove capacity harness guards on assertions; restore source bytes each time."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .resources import available_mib

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Mutation:
    name: str
    file: str
    old: str
    new: str
    test: str


def mutations() -> list[Mutation]:
    return [
        Mutation(
            "photo cleaning on loop",
            "src/gulbot/services/share_page_photos.py",
            "photo = await run_cpu(clean_photo, raw)",
            "photo = clean_photo(raw)",
            "tests/test_cp25_nonblocking.py::test_photo_cleaning_is_off_loop_but_session_writes_are_on_loop",
        ),
        Mutation(
            "logo normalisation on loop",
            "src/gulbot/services/shop_logo.py",
            "png, width, height = await run_cpu(normalise, data)",
            "png, width, height = normalise(data)",
            "tests/test_cp25_nonblocking.py::test_logo_normalisation_and_decoding_are_off_loop",
        ),
        Mutation(
            "logo decode on loop",
            "src/gulbot/services/shop_logo.py",
            "return await run_cpu(decode_logo, data)",
            "return decode_logo(data)",
            "tests/test_cp25_nonblocking.py::test_logo_normalisation_and_decoding_are_off_loop",
        ),
        Mutation(
            "spelling extraction on loop",
            "src/gulbot/services/announcements.py",
            "fields = await run_cpu(\n        extract,",
            "fields = extract(",
            "tests/test_cp25_nonblocking.py::test_cold_spelling_extraction_is_off_loop",
        ),
        Mutation(
            "legacy overlay on loop",
            "src/gulbot/bot/routers/announcements.py",
            "rendered = await run_cpu(\n            overlay,",
            "rendered = overlay(",
            "tests/test_cp25_nonblocking.py::test_legacy_overlay_is_off_loop",
        ),
        Mutation(
            "loop lag not reported",
            "src/gulbot/bot/loop_lag.py",
            "return lag if lag > self.threshold else None",
            "return None",
            "tests/test_cp25_loop_lag.py::test_delayed_loop_is_reported_and_normal_timing_recovers",
        ),
        Mutation(
            "night precheck bypassed",
            "tonight.py",
            "if free < 3072:",
            "if False:",
            "tests/test_cp25_tonight.py::test_tonight_precheck_records_refusal_without_launch",
        ),
        Mutation(
            "night runtime floor bypassed",
            "tonight.py",
            "if available_mib() < 512:",
            "if False:",
            "tests/test_cp25_tonight.py::test_runtime_floor_stops_only_the_returned_child",
        ),
        Mutation(
            "small scale excluded",
            "load_seed.py",
            "(2, 10, 25, 50, 100, 500, 1000)",
            "(2, 25, 50, 100, 500, 1000)",
            "tests/test_cp25_small_scales.py::test_small_scale_reaches_the_owned_seed_boundary[10]",
        ),
        Mutation(
            "unbounded scale admitted",
            "load_seed.py",
            "(2, 10, 25, 50, 100, 500, 1000)",
            "(2, 10, 11, 25, 50, 100, 500, 1000)",
            "tests/test_cp25_small_scales.py::test_unapproved_scale_never_resets_a_database[11]",
        ),
        Mutation(
            "heavy startup floor bypassed",
            "capacity.py",
            "if shops >= 100 and free < 3072:",
            "if False:",
            "tests/test_cp25_small_scales.py::test_heavy_scale_requires_three_gib_before_seed",
        ),
        Mutation(
            "per-target reconciliation removed",
            "validation.py",
            "if actual != expected:",
            "if False:",
            "tests/test_cp25_delivery.py::test_delivery_total_cannot_hide_missing_shop_with_duplicate[4]",
        ),
        Mutation(
            "foreign delivery ignored",
            "validation.py",
            'if reply["method"] in ("sendMessage", "sendPhoto"):',
            'if key in expected and reply["method"] in ("sendMessage", "sendPhoto"):',
            "tests/test_cp25_delivery.py::test_extra_cross_shop_delivery_cannot_be_silently_ignored",
        ),
        Mutation(
            "readiness memory floor removed",
            "capacity.py",
            "if free < 512:",
            "if False:",
            "tests/test_cp25_memory_guard.py::CoordinatorMemoryTests::test_readiness_does_not_bypass_ram_floor",
        ),
        Mutation(
            "fake API shutdown not awaited",
            "fleet_api.py",
            "        await api.close()",
            "        pass  # mutant skips close",
            "tests/test_cp25_api_shutdown.py::ApiShutdownTests::test_resource_report_is_published_after_api_close",
        ),
        Mutation(
            "reset and children bypass lease",
            "capacity.py",
            "async with database_lease():",
            "if True:",
            "tests/test_cp25_lease_lifetime.py::test_reset_and_children_cannot_start_without_lease",
        ),
        Mutation(
            "public reminder body bypassed",
            "load_roles.py",
            "await asyncio.to_thread(tasks.send_due_reminders.run)",
            "await tasks._send_due_reminders()",
            "tests/test_cp25_worker_lifetime.py::WorkerLifecycleTests::test_worker_exercises_public_task_bodies_on_distinct_closed_loops",
        ),
        Mutation(
            "reply flood also affects polling",
            "fleet_api.py",
            "if methods is not None and method not in methods:",
            "if False:",
            "tests/test_cp25_fleet_api.py::FleetProtocolTests::test_reply_only_flood_does_not_fake_a_polling_failure",
        ),
    ]


def main() -> None:
    from gulbot.config import get_settings

    settings = get_settings()
    if settings.postgres_test_db != "gulbot_cp25_test" or settings.redis_db_test != 8:
        raise SystemExit("Harness mutation proof requires CP25-only test resources")
    known = {m.name: m for m in mutations()}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=list(known))
    parser.add_argument(
        "--report", type=Path, default=ROOT / "docs" / "CP25_HARNESS_MUTATIONS.json"
    )
    args = parser.parse_args()
    selected = [m for m in known.values() if not args.only or m.name in args.only]
    report = args.report.resolve()
    if not report.is_relative_to(ROOT / "docs"):
        raise SystemExit("Mutation reports stay inside docs")
    results: list[dict[str, Any]] = []
    if args.only and report.exists():
        results = [
            r
            for r in json.loads(report.read_text(encoding="utf-8"))["results"]
            if r["guard"] not in args.only
            and r["guard"] in known
            and r["test"] == known[r["guard"]].test
        ]
    for mutation in selected:
        if available_mib() < 640:
            raise SystemExit("Insufficient RAM for the next small guard process")
        path = (
            (ROOT / mutation.file)
            if mutation.file.startswith("src/")
            else Path(__file__).resolve().parent / mutation.file
        )
        original = path.read_bytes()
        source = original.decode("utf-8").replace("\r\n", "\n")
        if source.count(mutation.old) != 1:
            raise SystemExit(f"Nonunique mutation anchor: {mutation.name}")
        try:
            path.write_text(source.replace(mutation.old, mutation.new), encoding="utf-8")
            run = subprocess.run(
                [sys.executable, "-m", "pytest", mutation.test, "-x", "--tb=short"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"},
            )
            output = run.stdout + run.stderr
            caught = run.returncode == 1 and bool(
                re.search(r"E\s+(?:assert|AssertionError)", output)
            )
            results.append(
                {
                    "guard": mutation.name,
                    "test": mutation.test,
                    "assertion_caught": caught,
                    "exit_code": run.returncode,
                }
            )
            print(f"{mutation.name}: {'assertion caught' if caught else 'NOT PROVEN'}", flush=True)
            if not caught:
                print(output[-2500:])
        finally:
            path.write_bytes(original)
        assert path.read_bytes() == original, "Mutation source restore failed"
    report.write_text(
        json.dumps(
            {
                "scope": "CP25 assertion guards (scope defined by each file/test)",
                "caught": sum(r["assertion_caught"] for r in results),
                "total": len(results),
                "results": results,
                "last_rechecked_guards": [m.name for m in selected],
                "report_scope": "Accumulated per-guard proof" if args.only else "Complete sweep",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not all(r["assertion_caught"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
