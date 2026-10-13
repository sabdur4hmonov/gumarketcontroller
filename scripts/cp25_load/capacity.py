"""CP25 capacity harness preparation; run only after Phase A completes.

Real production polling/handlers/outboxes against a localhost-only API and
owned Postgres/Redis fixtures. No STT download or Telegram connection.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, cast

import aiohttp

from .resources import Resources, atomic_json, available_mib, percentile
from .validation import reconcile_deliveries, validate_outboxes


async def require_ram() -> None:
    free = await asyncio.to_thread(available_mib)
    if free < 512:
        raise RuntimeError(f"Aborting owned capacity job: free RAM {free:.0f} MiB below 512")


async def guarded_pause(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        await require_ram()
        await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
    await require_ram()


async def wait_file(
    path: Path, child: subprocess.Popen[Any], seconds: float = 120
) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        await require_ram()
        if await asyncio.to_thread(path.exists):
            return cast(
                dict[str, Any],
                json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8")),
            )
        if child.poll() is not None:
            raise RuntimeError(
                f"Harness child exited {child.returncode}; inspect its private local log"
            )
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Harness child readiness timed out: {path.name}")


def launch(
    role: str, output: Path, *, api: str = "", shops: int = 0
) -> tuple[subprocess.Popen[Any], Any]:
    log = (output / f"{role}.log").open("wb")
    child = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "scripts.cp25_load.capacity",
            "--role",
            role,
            "--output",
            str(output),
            "--api",
            api,
            "--shops",
            str(shops),
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    return child, log


async def run_scale(shops: int, output: Path, fault: str) -> dict[str, Any]:
    from .infrastructure import Infrastructure
    from .load_lease import database_lease

    resources = Resources()
    async with database_lease():
        await require_ram()
        infra = Infrastructure()
        await infra.sample()
        watcher = asyncio.create_task(infra.watch())
        try:
            result = await _run_owned_scale(shops, output, fault)
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        await infra.sample()
        infra.finished = time.perf_counter()
        result["infrastructure"] = infra.result()
        result["coordinator_process"] = resources.result()
        await require_ram()
        await asyncio.to_thread(atomic_json, output / "result.json", result)
        return result


async def _run_owned_scale(shops: int, output: Path, fault: str) -> dict[str, Any]:
    from .load_seed import BOT_BASE, OWNER_BASE, USER_BASE, seed

    free = await asyncio.to_thread(available_mib)
    if shops >= 100 and free < 3072:
        raise RuntimeError(f"Heavy scales need 3072 MiB free; measured {free:.0f}")
    if free < 1024:
        raise RuntimeError(f"Capacity job needs at least 1024 MiB free; measured {free:.0f}")
    print(f"Scale {shops}: free RAM {free:.0f} MiB; DB gulbot_cp25_load; Redis FSM15", flush=True)
    os.environ["CP25_RUN_ID"] = uuid.uuid4().hex
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    os.environ["CP25_CRASH_FILE"] = (
        str((output / "crash-shop-1").resolve()) if fault == "crash" else ""
    )
    await asyncio.to_thread(seed, shops)
    children: list[tuple[subprocess.Popen[Any], Any]] = []
    enqueued: dict[tuple[int, int], int] = {}
    try:
        api_child, log = await asyncio.to_thread(launch, "api", output)
        children.append((api_child, log))
        api = (await wait_file(output / "api-ready.json", api_child))["url"]
        bot_child, log = await asyncio.to_thread(launch, "bot", output, api=api, shops=shops)
        children.append((bot_child, log))
        ready = await wait_file(output / "bots-ready.json", bot_child, seconds=max(120, shops * 2))
        assert ready["shops"] == shops, "Every synthetic shop must start"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as http:
            # All shops must have actually reached getUpdates, not merely have
            # an asyncio task scheduled by ShopPollers.sync.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                await require_ram()
                async with http.get(api + "/control/stats") as response:
                    stats = await response.json()
                if stats["polled_shops"] == shops:
                    break
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("Not every shop reached real HTTP long polling")
            if fault != "none":
                if fault == "crash":
                    await asyncio.to_thread((output / "crash-shop-1").touch)
                fault_request: dict[str, Any] = {"bot_id": BOT_BASE + 1, "mode": fault}
                if fault == "flood":
                    fault_request["methods"] = ["sendMessage", "sendPhoto", "sendMediaGroup"]
                elif fault == "poll-flood":
                    fault_request.update(mode="flood", methods=["getUpdates"])
                async with http.post(api + "/control/fault", json=fault_request) as response:
                    response.raise_for_status()
            worker_child, log = await asyncio.to_thread(
                launch, "worker", output, api=api, shops=shops
            )
            children.append((worker_child, log))
            for wave in range(3):
                updates = []
                started_ns = time.perf_counter_ns()
                for shop in range(1, shops + 1):
                    bot_id, user_id = BOT_BASE + shop, USER_BASE + wave * 10000 + shop
                    enqueued[(bot_id, user_id)] = started_ns
                    updates.append(
                        {
                            "bot_id": bot_id,
                            "update": {
                                "update_id": wave * 100 + 1,
                                "message": {
                                    "message_id": wave * 100 + 1,
                                    "date": int(time.time()),
                                    "chat": {"id": user_id, "type": "private"},
                                    "from": {
                                        "id": user_id,
                                        "is_bot": False,
                                        "first_name": "CP25 customer",
                                    },
                                    "text": "/start",
                                },
                            },
                        }
                    )
                    if wave == 0:
                        owner_id = OWNER_BASE + shop
                        enqueued[(bot_id, owner_id)] = started_ns
                        updates.append(
                            {
                                "bot_id": bot_id,
                                "update": {
                                    "update_id": 2,
                                    "callback_query": {
                                        "id": f"cp25-owner-{shop}",
                                        "chat_instance": f"cp25-{shop}",
                                        "from": {
                                            "id": owner_id,
                                            "is_bot": False,
                                            "first_name": "CP25 owner",
                                        },
                                        "data": f"ann:publish:{shop}:1:",
                                        "message": {
                                            "message_id": 1,
                                            "date": int(time.time()),
                                            "chat": {"id": owner_id, "type": "private"},
                                            "from": {
                                                "id": bot_id,
                                                "is_bot": True,
                                                "first_name": "CP25 fake",
                                            },
                                            "text": "Confirmed preview",
                                        },
                                    },
                                },
                            }
                        )
                async with http.post(
                    api + "/control/updates", json={"updates": updates}
                ) as response:
                    response.raise_for_status()
                await guarded_pause(10)
            expected = (shops - int(fault != "none")) * 4
            # Include fresh per-task bot construction and session shutdown in
            # the baseline; a short harness deadline is not a fleet capacity limit.
            deadline = time.monotonic() + max(180, shops * 4)
            while time.monotonic() < deadline:
                if bot_child.poll() is not None:
                    raise RuntimeError("Bot process stopped during the measured workload")
                await require_ram()
                async with http.get(api + "/control/stats") as response:
                    stats = await response.json()
                seen: dict[tuple[int, int], int] = {}
                for reply in stats["replies"]:
                    key = (reply["bot_id"], reply["chat_id"])
                    if (
                        key in enqueued
                        and key not in seen
                        and reply["role"] in ("customer", "owner")
                        and reply["received_ns"] >= enqueued[key]
                    ):
                        seen[key] = reply["received_ns"]
                healthy = {
                    key: stamp
                    for key, stamp in seen.items()
                    if fault == "none" or key[0] != BOT_BASE + 1
                }
                if len(healthy) == expected and worker_child.poll() is not None:
                    break
                await asyncio.sleep(0.25)
            else:
                raise TimeoutError(f"Workload incomplete: {len(healthy)}/{expected} replies")
            if worker_child.returncode != 0:
                raise RuntimeError("Outbox worker failed; results are not valid capacity evidence")
        latencies = [(stamp - enqueued[key]) / 1000000 for key, stamp in healthy.items()]
        await asyncio.to_thread((output / "stop-bots").touch)
        bot_metrics = await wait_file(
            output / "bot-metrics.json", bot_child, seconds=30 + shops * 0.3
        )
        worker_metrics = json.loads(
            await asyncio.to_thread((output / "worker-metrics.json").read_text, encoding="utf-8")
        )
        # A polling-only refusal leaves that shop's outgoing API usable.
        expected_outbox_shops = shops - int(fault not in ("none", "poll-flood", "crash"))
        validate_outboxes(worker_metrics, expected_outbox_shops)
        reconcile_deliveries(stats["replies"], shops=shops, fault=fault)
        await asyncio.to_thread((output / "stop-api").touch)
        api_metrics = await wait_file(output / "api-resources.json", api_child, seconds=30)
        result = {
            "shops": shops,
            "fault": fault,
            "healthy_replies": len(healthy),
            "expected_healthy_replies": expected,
            "expected_reminder_sends": expected_outbox_shops,
            "expected_order_sends": expected_outbox_shops,
            "p50_ms": percentile(latencies, 50),
            "p95_ms": percentile(latencies, 95),
            "p99_ms": percentile(latencies, 99),
            "customer_updates_per_shop": 3,
            "owner_announcements_per_shop": 1,
            "wave_interval_s": 10,
            "fake_api_delay_ms": 5,
            "bot": bot_metrics,
            "worker": worker_metrics,
            "api_process": api_metrics,
            "api_calls": stats["calls"],
            "peak_polls": stats["peak_polls"],
            "telegram_uploads": stats["uploads"],
            "telegram_upload_bytes": stats["upload_bytes"],
        }
        return result
    finally:
        await asyncio.to_thread((output / "stop-bots").touch)
        await asyncio.to_thread((output / "stop-api").touch)
        for child, log in children:
            if child.poll() is None:
                child.terminate()
                try:
                    await asyncio.to_thread(child.wait, timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    await asyncio.to_thread(child.wait, timeout=5)
            log.close()
        # Remove only this run's own FSM namespace. Never FLUSHDB.
        from redis.asyncio import Redis

        from gulbot.config import get_settings

        redis = Redis.from_url(get_settings().redis_url(15))
        try:
            owned = []
            async for key in redis.scan_iter(match="cp25-load:" + os.environ["CP25_RUN_ID"] + ":*"):
                owned.append(key)
                if len(owned) >= 500:
                    await redis.unlink(*owned)
                    owned.clear()
            if owned:
                await redis.unlink(*owned)
        finally:
            await redis.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("all", "api", "bot", "worker"), default="all")
    parser.add_argument("--scales", default="100,500,1000")
    parser.add_argument("--shops", type=int, default=0)
    parser.add_argument("--api", default="")
    parser.add_argument(
        "--fault",
        choices=("none", "unauthorized", "network", "flood", "poll-flood", "stall", "crash"),
        default="none",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Set synthetic credentials BEFORE importing any module which constructs
    # the Celery app and caches get_settings during import.
    if args.role == "all":
        from cryptography.fernet import Fernet

        os.environ["SHOP_TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    if "SHOP_TOKEN_ENCRYPTION_KEY" not in os.environ:
        raise SystemExit("Harness children require their synthetic encryption key")
    os.environ.update(
        {
            "ENVIRONMENT": "local",
            "BOT_TOKEN": "",
            "PLATFORM_BOT_TOKEN": "",
            "POSTGRES_DB": "gulbot_cp25_load",
            "POSTGRES_TEST_DB": "gulbot_cp25_test",
            "REDIS_DB_BROKER": "6",
            "REDIS_DB_RESULTS": "7",
            "REDIS_DB_FSM": "15",
            "REDIS_DB_TEST": "8",
            "INSTAGRAM_PUBLISHING_ENABLED": "false",
        }
    )

    if args.role == "api":
        from .fleet_api import api_role

        asyncio.run(api_role(args.output))
    elif args.role == "bot":
        from .load_roles import bot_role

        asyncio.run(bot_role(args.api, args.output))
    elif args.role == "worker":
        from .load_roles import worker_role

        asyncio.run(worker_role(args.api, args.output, args.shops))
    else:
        results = []
        for scale in map(int, args.scales.split(",")):
            results.append(asyncio.run(run_scale(scale, args.output / str(scale), args.fault)))
        atomic_json(args.output / "summary.json", results)


if __name__ == "__main__":
    main()
