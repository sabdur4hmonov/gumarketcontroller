"""Fail idle incomplete workloads early, while preserving all passing requirements."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

STALL_SECONDS = 120


def stalled_replies(
    stats: dict[str, Any], expected: int, now_ns: int, started_ns: int, *, worker_finished: bool
) -> int | None:
    replies = [r for r in stats["replies"] if r["role"] in {"customer", "owner"}]
    delivered = len({(r["bot_id"], r["chat_id"]) for r in replies})
    latest = max((int(r["received_ns"]) for r in replies), default=started_ns)
    if not worker_finished or delivered >= expected:
        return None
    if now_ns - latest < STALL_SECONDS * 1_000_000_000:
        return None
    return delivered


def inspect_stall(directory: Path, shops: int, started_ns: int) -> dict[str, Any] | None:
    worker_file = directory / "worker-metrics.json"
    if not worker_file.is_file():
        return None
    endpoint = json.loads((directory / "api-ready.json").read_text(encoding="utf-8"))["url"]
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise ValueError("Progress inspection requires the owned localhost API")
    with urlopen(endpoint + "/control/stats", timeout=1) as response:
        stats = json.load(response)
    expected = shops * 4
    count = stalled_replies(
        stats, expected, time.perf_counter_ns(), started_ns, worker_finished=True
    )
    if count is None:
        return None
    worker = json.loads(worker_file.read_text(encoding="utf-8"))
    last = max(
        (int(r["received_ns"]) for r in stats["replies"] if r["role"] in {"customer", "owner"}),
        default=started_ns,
    )
    return {
        "kind": "failed incomplete workload; no capacity quantiles certified",
        "successful_replies": count,
        "expected_replies": expected,
        "no_progress_seconds": STALL_SECONDS,
        "actual_no_progress_seconds": (time.perf_counter_ns() - last) / 1_000_000_000,
        "api_stats": stats,
        "runtime_provenance": worker["runtime_provenance"],
    }
