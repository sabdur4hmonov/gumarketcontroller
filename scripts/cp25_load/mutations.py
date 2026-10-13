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
    reliability = (ROOT / "src/gulbot/bot/reliability.py").read_text(encoding="utf-8")
    retry = reliability[
        reliability.index("        for attempt in range(3):") : reliability.index(
            '        raise RuntimeError("Unreachable reply retry state")'
        )
    ]
    migration_file = "migrations/versions/a25e1d6c8b90_shop_runtime_states.py"
    migration = (ROOT / migration_file).read_text(encoding="utf-8")
    upgrade = migration[migration.index("def upgrade()") : migration.index("def downgrade()")]
    return [
        Mutation(
            "worker loses tick-owned lookup",
            "src/gulbot/worker/tasks.py",
            "lookup=BouquetLookup()",
            "lookup=None",
            "tests/test_cp25_data_efficiency.py::test_worker_shares_lookup_inside_tick_and_rebuilds_it_next_tick",
        ),
        Mutation(
            "plan collection ignores ownership",
            "query_plans.py",
            "if marker != OWNER_MARKER:",
            "if False:",
            "tests/test_cp25_query_plans.py::test_explain_admission_rejects_before_fixture_writes[foreign-10]",
        ),
        Mutation(
            "plan collection accepts large fleet",
            "query_plans.py",
            "if not 0 < shops <= 50:",
            "if False:",
            "tests/test_cp25_query_plans.py::test_explain_admission_rejects_before_fixture_writes[gulbot-cp25-capacity-fixtures-only-51]",
        ),
        Mutation(
            "worker pool enlarged",
            "src/gulbot/db/session.py",
            "pool_size=settings.postgres_task_pool_size if task else settings.postgres_pool_size,",
            "pool_size=settings.postgres_pool_size,",
            "tests/test_cp25_data_efficiency.py::test_task_pool_is_small_without_shrinking_the_bot_pool",
        ),
        Mutation(
            "worker overflow enabled",
            "src/gulbot/db/session.py",
            "max_overflow=0 if task else settings.postgres_pool_overflow,",
            "max_overflow=settings.postgres_pool_overflow,",
            "tests/test_cp25_data_efficiency.py::test_task_pool_is_small_without_shrinking_the_bot_pool",
        ),
        Mutation(
            "pool wait unbounded",
            "src/gulbot/db/session.py",
            "pool_timeout=5,",
            "pool_timeout=None,",
            "tests/test_cp25_data_efficiency.py::test_pool_and_connect_waits_are_bounded",
        ),
        Mutation(
            "DB connect deadline removed",
            "src/gulbot/db/session.py",
            '"timeout": 10,',
            '"timeout": None,',
            "tests/test_cp25_data_efficiency.py::test_pool_and_connect_waits_are_bounded",
        ),
        Mutation(
            "catalogue cache loses tenancy",
            "src/gulbot/sending/attach.py",
            "key = (shop_id, preference)",
            "key = (0, preference)",
            "tests/test_cp25_data_efficiency.py::test_bouquet_cache_is_per_tick_and_per_shop_and_preference",
        ),
        Mutation(
            "catalogue cache loses preference",
            "src/gulbot/sending/attach.py",
            "key = (shop_id, preference)",
            "key = (shop_id, None)",
            "tests/test_cp25_data_efficiency.py::test_bouquet_cache_is_per_tick_and_per_shop_and_preference",
        ),
        Mutation(
            "catalogue choice queried per customer",
            "src/gulbot/sending/attach.py",
            "if key not in self.choices:",
            "if True:",
            "tests/test_cp25_data_efficiency.py::test_bouquet_cache_is_per_tick_and_per_shop_and_preference",
        ),
        Mutation(
            "catalogue choice survives tick",
            "src/gulbot/sending/attach.py",
            "self.choices: dict[tuple[int, str | None], Bouquet | None] = {}",
            "if not hasattr(type(self), '_mutant_choices'):\n"
            "            type(self)._mutant_choices = {}\n"
            "        self.choices = type(self)._mutant_choices",
            "tests/test_cp25_data_efficiency.py::test_bouquet_cache_is_per_tick_and_per_shop_and_preference",
        ),
        Mutation(
            "cursor index omitted",
            "migrations/versions/a25f2c7d9e10_catalog_cursor_index.py",
            "def upgrade() -> None:\n    with op.get_context().autocommit_block():",
            "def upgrade() -> None:\n    return\n    with op.get_context().autocommit_block():",
            "tests/test_cp25_catalog_index.py::test_cursor_index_roundtrips_without_changing_existing_tables",
        ),
        Mutation(
            "cursor predicate admits provisional products",
            "migrations/versions/a25f2c7d9e10_catalog_cursor_index.py",
            "active IS TRUE AND deleted_at IS NULL AND finalized_at IS NOT NULL",
            "active IS TRUE AND deleted_at IS NULL",
            "tests/test_cp25_catalog_index.py::test_cursor_index_roundtrips_without_changing_existing_tables",
        ),
        Mutation(
            "runtime additive table omitted",
            migration_file,
            upgrade,
            "def upgrade() -> None:\n    pass\n\n\n",
            "tests/test_cp25_runtime_schema.py::test_runtime_schema_is_additive_on_a_fresh_database",
        ),
        Mutation(
            "admin quantile changed",
            "src/gulbot/bot/reliability.py",
            "position = (len(ordered) - 1) * 0.95",
            "position = (len(ordered) - 1) * 1.0",
            "tests/test_cp25_reliability.py::test_handler_p95_uses_the_same_interpolated_quantile_as_capacity",
        ),
        Mutation(
            "handler deadline bypassed",
            "src/gulbot/bot/reliability.py",
            "return await asyncio.wait_for(handler(event, data), timeout=self.seconds)",
            "return await handler(event, data)",
            "tests/test_cp25_reliability.py::test_stuck_handler_is_bounded_and_session_rolls_back",
        ),
        Mutation(
            "cancellation rollback skipped",
            "src/gulbot/bot/middlewares.py",
            "except BaseException:",
            "except Exception:",
            "tests/test_cp25_reliability.py::test_stuck_handler_is_bounded_and_session_rolls_back",
        ),
        Mutation(
            "reply pacing removed",
            "src/gulbot/bot/reliability.py",
            "interval = 3 if numeric_chat < 0 else 1",
            "interval = 0",
            "tests/test_cp25_reliability.py::test_replies_in_one_chat_are_paced_without_delaying_another_bot",
        ),
        Mutation(
            "429 not retried",
            "src/gulbot/bot/reliability.py",
            "if attempt == 2 or self.clock() + wait > deadline:",
            "if True:",
            "tests/test_cp25_reliability.py::test_429_waits_then_retries_only_the_same_request",
        ),
        Mutation(
            "429 retry cap widened",
            "src/gulbot/bot/reliability.py",
            retry,
            retry.replace("range(3)", "range(4)").replace("attempt == 2", "attempt == 3"),
            "tests/test_cp25_reliability.py::test_permanent_429_is_bounded",
        ),
        Mutation(
            "poll progress failure not recorded",
            "src/gulbot/bot/reliability.py",
            "self.progress.consecutive_failures += 1",
            "pass",
            "tests/test_cp25_reliability.py::test_poll_failure_and_recovery_update_progress_without_reply_noise",
        ),
        Mutation(
            "crashed poller ignored",
            "src/gulbot/bot/run.py",
            "if poller.task.done():",
            "if False:",
            "tests/test_cp25_watchdog.py::test_crashed_poller_is_detected_without_touching_the_healthy_shop",
        ),
        Mutation(
            "stalled poller ignored",
            "src/gulbot/bot/run.py",
            "elif now - poller.progress.last_progress > 90:",
            "elif False:",
            "tests/test_cp25_watchdog.py::test_stall_backoff_and_restart_use_injected_time",
        ),
        Mutation(
            "restart backoff bypassed",
            "src/gulbot/bot/run.py",
            "if self._clock() < self._retry_at.get(shop_id, 0):",
            "if False:",
            "tests/test_cp25_watchdog.py::test_stall_backoff_and_restart_use_injected_time",
        ),
        Mutation(
            "backoff cap removed",
            "src/gulbot/bot/run.py",
            "delay = min(60, 2 ** min(count - 1, 6))",
            "delay = 2 ** min(count - 1, 6)",
            "tests/test_cp25_watchdog.py::test_stall_backoff_and_restart_use_injected_time",
        ),
        Mutation(
            "runtime state not persisted",
            "src/gulbot/services/runtime_state.py",
            "if not states:",
            "if True:",
            "tests/test_cp25_runtime_view.py::test_runtime_store_is_shop_scoped_and_admin_reports_backoff",
        ),
        Mutation(
            "admin ignores poller failure",
            "src/gulbot/services/admin_panel.py",
            'if runtime.get("status") in {"backoff", "stalled", "crashed", "start_error"}:',
            "if False:",
            "tests/test_cp25_runtime_view.py::test_runtime_store_is_shop_scoped_and_admin_reports_backoff",
        ),
        Mutation(
            "crash injection removed",
            "load_roles.py",
            'raise asyncio.CancelledError("one-shot synthetic poller crash")',
            "pass",
            "tests/test_cp25_crash_hook.py::test_crash_is_one_shot_and_only_the_bad_shop",
        ),
        Mutation(
            "factory crash stops fleet",
            "src/gulbot/bot/run.py",
            'self._report(shop_id, f"factory_error:{type(error).__name__}")',
            "raise",
            "tests/test_cp25_poll_isolation.py::test_unexpected_factory_error_is_isolated",
        ),
        Mutation(
            "TLS constructor blocks loop",
            "src/gulbot/bot/run.py",
            "bot = await asyncio.wait_for(\n"
            "                    run_cpu(self._bot_factory, token_for(shop_id)), timeout=20\n"
            "                )",
            "bot = self._bot_factory(token_for(shop_id))",
            "tests/test_cp25_poll_isolation.py::test_bot_constructor_cannot_block_the_polling_loop",
        ),
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
            if mutation.file.startswith(("src/", "migrations/"))
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
