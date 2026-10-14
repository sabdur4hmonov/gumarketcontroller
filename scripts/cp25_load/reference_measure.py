"""Run unchanged production sources with isolated fixtures and explicit provenance.

This entry point is run as a file, not -m: the chosen checkout must own the
scripts/gulbot imports too. Only harness resource routing and engine-meter
keyword forwarding are adapted. Optional profiles are diagnostic, not baseline.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import cProfile
import hashlib
import importlib.metadata
import json
import marshal
import math
import os
import pstats
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
ENTRY = Path(__file__).resolve()
BEFORE = "f8f73b8405322ec99cb1e06305fc9f7330f31df0"
REFERENCE = ROOT.parent / "gulbot-cp25-before"
PROFILES: dict[str, list[dict[str, Any]]] = defaultdict(list)
CERTIFICATE: dict[str, Any] = {}


def scale_gate(shops: int, measured_peak: float | None = None) -> int:
    if shops >= 100:
        return 3072
    if shops == 2:
        return 1024
    if measured_peak is None:
        return 3072
    if not math.isfinite(measured_peak) or measured_peak < 0:
        raise ValueError("Admission peak must be measured, finite and nonnegative")
    return math.ceil(measured_peak + 1024)


def seed_startup(shops: int, seed_function: Any) -> None:
    if shops != 2:
        raise ValueError("Startup-only seed must remain2 shops; no capacity role is run")
    seed_function(2)


def note(message: str) -> None:
    with (ROOT / "docs/CP25_STATUS.md").open("a", encoding="utf-8") as stream:
        stream.write("\n" + datetime.now(UTC).isoformat() + " — " + message + "\n")


def resources(phase: str) -> dict[str, str]:
    if phase == "before":
        return {
            "POSTGRES_DB": "gulbot_cp25_before_load",
            "POSTGRES_TEST_DB": "gulbot_cp25_before_test",
            "REDIS_DB_BROKER": "9",
            "REDIS_DB_RESULTS": "10",
            "REDIS_DB_FSM": "12",
            "REDIS_DB_TEST": "11",
        }
    if phase == "after":
        return {
            "POSTGRES_DB": "gulbot_cp25_load",
            "POSTGRES_TEST_DB": "gulbot_cp25_test",
            "REDIS_DB_BROKER": "6",
            "REDIS_DB_RESULTS": "7",
            "REDIS_DB_FSM": "15",
            "REDIS_DB_TEST": "8",
        }
    raise ValueError("Only before/after resources are permitted")


def git(source: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(source), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    ).stdout.rstrip("\r\n")


def provenance(source: Path, phase: str) -> dict[str, Any]:
    commit = git(source, "rev-parse", "HEAD")
    dirty = git(source, "status", "--porcelain")
    if phase == "before" and (commit != BEFORE or dirty):
        raise ValueError("Pre-change production checkout must be clean at frozen f8f73b8")
    paths = sorted([*(source / "src").rglob("*.py"), *(source / "migrations").rglob("*.py")])
    hashes = {
        p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
    }
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    executed = {}
    for directory in (source / "src", source / "scripts/cp25_load"):
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            checksum = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1_048_576), b""):
                    checksum.update(chunk)
            executed[path.relative_to(source).as_posix()] = checksum.hexdigest()
    return {
        "production_commit": commit,
        "production_dirty": bool(dirty),
        "production_tree_sha256": digest,
        "production_file_sha256": hashes,
        "git_status_porcelain": dirty,
        "executed_tree_sha256": hashlib.sha256(
            json.dumps(executed, sort_keys=True).encode()
        ).hexdigest(),
        "executed_file_sha256": executed,
        "measurement_adapter_sha256": hashlib.sha256(ENTRY.read_bytes()).hexdigest(),
        "measurement_adapter": "resource routing, launch entry and engine-meter kwargs only",
        "dependencies": sorted(
            [(d.metadata["Name"], d.version) for d in importlib.metadata.distributions()]
        ),
        "resources": resources(phase),
    }


def write_certified(path: Path, data: Any, certificate: dict[str, Any]) -> None:
    if isinstance(data, dict):
        data = {**data, "runtime_provenance": certificate}
    elif isinstance(data, list):
        data = [{**row, "runtime_provenance": certificate} for row in data]
    else:
        raise ValueError("Only dict/list result payloads are supported")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def checked_revision(actual: list[str], expected: list[str]) -> str:
    if actual != expected or len(expected) != 1:
        raise RuntimeError("Fixture schema does not match the measured checkout")
    return actual[0]


def fixture_revision(source: Path, seed_module: Any) -> str:
    """Certify real DB schema, not just imported Python filenames."""
    import psycopg
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from gulbot.config import get_settings

    config = Config(str(source / "alembic.ini"))
    config.set_main_option("script_location", str(source / "migrations"))
    expected = ScriptDirectory.from_config(config).get_heads()
    dsn = (
        get_settings()
        .database_url(database=seed_module.DATABASE, driver="psycopg")
        .replace("postgresql+psycopg://", "postgresql://")
    )
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        actual = [
            r[0] for r in connection.execute("SELECT version_num FROM alembic_version").fetchall()
        ]
    return checked_revision(actual, expected)


def adapt_engine_meter(roles: Any) -> None:
    """Preserve task=True on current code; before's calls have no keywords.

    Do not replace the real production engine or inject pool defaults.
    """
    path = Path(roles.__file__)
    raw = path.read_text(encoding="utf-8")
    node = next(
        n
        for n in ast.parse(raw).body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "worker_role"
    )
    function = ast.get_source_segment(raw, node)
    if function is None:
        raise ValueError("Missing public worker harness function")
    old = "def measured_engine(database: str | None = None) -> AsyncEngine:"
    call = "engine = original_engine(DATABASE)"
    # Current harness forwards the production pool flag directly; frozen f8
    # needs only the legacy keyword adapter below. Never change either pool.
    if (
        function.count("def measured_engine(database: str | None = None, *, task: bool = False)")
        == 1
        and function.count("engine = original_engine(DATABASE, task=task)") == 1
    ):
        return
    if function.count(old) != 1 or function.count(call) != 1:
        raise ValueError("Engine meter changed; review the narrow adapter")
    function = function.replace(
        old, "def measured_engine(database: str | None = None, **options: Any) -> AsyncEngine:"
    )
    function = function.replace(call, "engine = original_engine(DATABASE, **options)")
    exec(compile(function, str(path) + " [measurement keyword adapter]", "exec"), roles.__dict__)


def adapt_cleanup(capacity: Any) -> None:
    """Keep the original prefix cleanup, targeting the isolated FSM index."""
    path = Path(capacity.__file__)
    raw = path.read_text(encoding="utf-8")
    node = next(
        n
        for n in ast.parse(raw).body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_owned_scale"
    )
    function = ast.get_source_segment(raw, node)
    old = "redis_url(15)"
    if function is None or function.count(old) != 1:
        raise ValueError("Review cleanup resource routing before running")
    function = function.replace(old, 'redis_url(int(os.environ["REDIS_DB_FSM"]))')
    function = function.replace(
        "DB gulbot_cp25_load; Redis FSM15",
        "DB {os.environ['POSTGRES_DB']}; Redis FSM{os.environ['REDIS_DB_FSM']}",
    )
    exec(
        compile(function, str(path) + " [measurement resource adapter]", "exec"), capacity.__dict__
    )


def profile_tasks(output: Path) -> None:
    """Separate real TLS/registry/limiter spans; cProfile covers public bodies."""
    from sqlalchemy import event

    from gulbot.bot.registry import BotRegistry
    from gulbot.db import session as session_module
    from gulbot.sending.rate_limit import RateLimiter
    from gulbot.sending.telegram import TelegramTransport
    from gulbot.worker import tasks

    spans: dict[str, list[float]] = defaultdict(list)
    original_bot = BotRegistry.bot_for
    original_close = BotRegistry.close
    original_acquire = RateLimiter.acquire
    original_engine = session_module.build_engine
    original_attempt = TelegramTransport._attempt

    def engine(*a: Any, **kw: Any) -> Any:
        started = time.perf_counter()
        made = original_engine(*a, **kw)
        spans["db_engine_build_wall_s"].append(time.perf_counter() - started)

        def connecting(dialect: Any, record: Any, args: Any, options: Any) -> None:
            record.info["cp25_connect_started"] = time.perf_counter()

        def connected(connection: Any, record: Any) -> None:
            spans["db_connection_setup_wall_s"].append(
                time.perf_counter() - record.info.pop("cp25_connect_started")
            )

        def before(
            connection: Any, cursor: Any, sql: Any, params: Any, context: Any, many: Any
        ) -> None:
            context.cp25_profile_started = time.perf_counter()

        def after(
            connection: Any, cursor: Any, sql: Any, params: Any, context: Any, many: Any
        ) -> None:
            spans["sql_query_wall_s"].append(time.perf_counter() - context.cp25_profile_started)

        for name, callback in (
            ("do_connect", connecting),
            ("connect", connected),
            ("before_cursor_execute", before),
            ("after_cursor_execute", after),
        ):
            event.listen(made.sync_engine, name, callback)
        return made

    async def attempt(self: Any, *a: Any, **kw: Any) -> Any:
        started = time.perf_counter()
        try:
            return await original_attempt(self, *a, **kw)
        finally:
            spans["telegram_transport_wall_s"].append(time.perf_counter() - started)

    def bot(self: Any, *a: Any, **kw: Any) -> Any:
        started = time.perf_counter()
        try:
            return original_bot(self, *a, **kw)
        finally:
            spans["registry_bot_for_wall_s"].append(time.perf_counter() - started)

    async def close(self: Any) -> None:
        started = time.perf_counter()
        try:
            await original_close(self)
        finally:
            spans["registry_close_wall_s"].append(time.perf_counter() - started)

    async def acquire(self: Any, *a: Any, **kw: Any) -> float:
        started = time.perf_counter()
        try:
            waited = await original_acquire(self, *a, **kw)
            spans["limiter_scheduled_wait_s"].append(waited)
            return waited
        finally:
            spans["limiter_acquire_wall_s"].append(time.perf_counter() - started)

    cast(Any, BotRegistry).bot_for = bot
    cast(Any, BotRegistry).close = close
    cast(Any, RateLimiter).acquire = acquire
    session_module.build_engine = engine
    cast(Any, TelegramTransport)._attempt = attempt

    def wrap(name: str, task: Any) -> None:
        original = task.run

        def measured(*args: Any, **kwargs: Any) -> Any:
            spans.clear()
            profiler = cProfile.Profile()
            started, cpu = time.perf_counter(), time.thread_time()
            profiler.enable()
            try:
                return original(*args, **kwargs)
            finally:
                profiler.disable()
                elapsed = time.perf_counter() - started
                seconds = time.thread_time() - cpu
                stats = pstats.Stats(profiler)
                rows = [
                    {
                        "file": key[0],
                        "line": key[1],
                        "function": key[2],
                        "primitive_calls": value[0],
                        "calls": value[1],
                        "self_s": value[2],
                        "cumulative_s": value[3],
                    }
                    for key, value in cast(Any, stats).stats.items()
                ]
                PROFILES[name].append(
                    {
                        "kind": "diagnostic profile; excluded from baseline table",
                        "wall_s": elapsed,
                        "thread_cpu_s": seconds,
                        "spans": {k: {"calls": len(v), "sum_s": sum(v)} for k, v in spans.items()},
                        "profile": sorted(rows, key=lambda r: r["cumulative_s"], reverse=True),
                    }
                )
                write_certified(output / "tick-profile.json", dict(PROFILES), CERTIFICATE)

        task.run = measured

    wrap("reminder", tasks.send_due_reminders)
    wrap("order", tasks.send_order_pings)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--role", choices=("all", "api", "bot", "worker", "seed"), default="all")
    parser.add_argument("--scales", default="10,25,50")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api", default="")
    parser.add_argument("--shops", type=int, default=0)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--small-peak-mib", type=float, default=None)
    args = parser.parse_args()
    source = args.source.resolve()
    expected = REFERENCE if args.phase == "before" else ROOT
    if source != expected.resolve():
        raise ValueError("Use only the approved reference checkout or current repository")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".cp22-stage/cp25"):
        raise ValueError("Measurement output must stay in owned ignored staging")
    os.chdir(source)  # Alembic.ini/script_location must belong to this checkout too.
    sys.path[:0] = [str(source / "src"), str(source)]
    # Never copy the private .env into a checkout. Forward only local DB/Redis
    # connection fields; disable real bot/Meta tokens before cached imports.
    from dotenv import dotenv_values

    connection_fields = {
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "REDIS_HOST",
        "REDIS_PORT",
    }
    for key, value in dotenv_values(ROOT / ".env").items():
        if key in connection_fields and value is not None:
            os.environ.setdefault(key, value)
    os.environ.update(
        {
            **resources(args.phase),
            "ENVIRONMENT": "local",
            "BOT_TOKEN": "",
            "PLATFORM_BOT_TOKEN": "",
            "INSTAGRAM_PUBLISHING_ENABLED": "false",
        }
    )
    from scripts.cp25_load.resources import available_mib

    if args.role in ("all", "seed"):
        free = available_mib()
        note(f"{args.phase} {args.scales}: precheck actual free RAM {free:.2f}MiB.")
        floor = (
            1024
            if args.role == "seed"
            else max(
                scale_gate(scale, args.small_peak_mib) for scale in map(int, args.scales.split(","))
            )
        )
        if free < floor:
            raise SystemExit(f"Measurement refused below{floor}MiB; no retry.")
        from cryptography.fernet import Fernet

        os.environ["SHOP_TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    elif "SHOP_TOKEN_ENCRYPTION_KEY" not in os.environ:
        raise SystemExit("Synthetic key must be inherited from this run")
    from scripts.cp25_load import capacity, load_roles, load_seed

    import gulbot

    if not Path(gulbot.__file__).resolve().is_relative_to(source / "src"):
        raise ValueError("Production imports escaped the measured checkout")
    load_seed.DATABASE = resources(args.phase)["POSTGRES_DB"]
    cast(Any, load_roles).DATABASE = load_seed.DATABASE
    load_roles.REDIS_INDEX = int(resources(args.phase)["REDIS_DB_FSM"])
    adapt_engine_meter(load_roles)
    adapt_cleanup(capacity)
    certificate = provenance(source, args.phase)
    certificate["profile_enabled"] = args.profile
    certificate["run_id"] = os.environ.get("CP25_RUN_ID")
    certificate["runtime_harness_code_sha256"] = {
        "worker_role": hashlib.sha256(marshal.dumps(load_roles.worker_role.__code__)).hexdigest(),
        "capacity": hashlib.sha256(marshal.dumps(capacity._run_owned_scale.__code__)).hexdigest(),
    }
    CERTIFICATE.update(certificate)
    if args.role not in ("all", "seed"):
        CERTIFICATE["database_revision"] = fixture_revision(source, load_seed)
    from scripts.cp25_load import resources as resource_module

    def certified(path: Path, data: Any) -> None:
        write_certified(path, data, CERTIFICATE)

    resource_module.atomic_json = certified
    cast(Any, capacity).atomic_json = certified
    cast(Any, load_roles).atomic_json = certified
    original_seed = load_seed.seed

    def seed(*a: Any, **kw: Any) -> None:
        original_seed(*a, **kw)
        CERTIFICATE["database_revision"] = fixture_revision(source, load_seed)

    load_seed.seed = seed

    def launch(
        role: str, output: Path, *, api: str = "", shops: int = 0
    ) -> tuple[subprocess.Popen[Any], Any]:
        stream = (output / f"{role}.log").open("wb")
        command = [
            sys.executable,
            "-u",
            str(ENTRY),
            "--source",
            str(source),
            "--phase",
            args.phase,
            "--role",
            role,
            "--output",
            str(output),
            "--api",
            api,
            "--shops",
            str(shops),
        ]
        if args.profile:
            command.append("--profile")
        child = subprocess.Popen(
            command,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUTF8": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return child, stream

    capacity.launch = launch
    if args.role == "seed":
        from scripts.cp25_load.resources import rss_mib

        output.mkdir(parents=True, exist_ok=False)
        seed_startup(args.shops, seed)
        certified(
            output / "seed.json",
            {
                "kind": "seed-only startup diagnostic; not capacity",
                "shops": 2,
                "peak_rss_mib": rss_mib(),
            },
        )
    elif args.role == "api":
        from scripts.cp25_load.fleet_api import api_role

        asyncio.run(api_role(output))
    elif args.role == "bot":
        asyncio.run(load_roles.bot_role(args.api, output))
    elif args.role == "worker":
        if args.profile:
            profile_tasks(output)
        asyncio.run(load_roles.worker_role(args.api, output, args.shops))
    else:
        manifest = provenance(source, args.phase)
        results = []
        for scale in map(int, args.scales.split(",")):
            # Every scale, including10/25/50, is separately admitted/recorded.
            free = available_mib()
            note(
                f"{args.phase}-{scale}: actual free RAM before scale {free:.2f}MiB; "
                f"source {manifest['production_commit']}."
            )
            floor = scale_gate(scale, args.small_peak_mib)
            if free < floor:
                raise SystemExit(f"Scale refused below{floor}MiB; no retry.")
            directory = output / str(scale)
            CERTIFICATE["precheck_free_mib"] = free
            result = asyncio.run(capacity.run_scale(scale, directory, "none"))
            result["runtime_provenance"] = dict(CERTIFICATE)
            certified(
                directory / "provenance.json",
                {**manifest, "precheck_free_mib": free, "profile_enabled": args.profile},
            )
            results.append(result)
            note(
                f"{args.phase}-{scale}: run completed; minimum sampled free RAM "
                f"{result['infrastructure']['min_sampled_free_mib']}MiB; "
                "validity not yet assessed."
            )
        write_certified(output / "summary.json", results, CERTIFICATE)


if __name__ == "__main__":
    main()
