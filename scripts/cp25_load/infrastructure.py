"""Sample only this project's Docker infrastructure, with bounded calls."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from typing import Any

from .resources import available_mib

CONTAINERS = ("gulbot-postgres", "gulbot-redis")


def memory_mib(value: str) -> float:
    match = re.fullmatch(r"([\d.]+)(B|kB|KB|KiB|MB|MiB|GB|GiB|TB|TiB)", value.strip())
    if match is None:
        raise ValueError("Unrecognised container memory unit")
    units = {
        "B": 1,
        "kB": 1000,
        "KB": 1000,
        "KiB": 1024,
        "MB": 1000**2,
        "MiB": 1024**2,
        "GB": 1000**3,
        "GiB": 1024**3,
        "TB": 1000**4,
        "TiB": 1024**4,
    }
    return float(match[1]) * units[match[2]] / 1048576


def docker_sample() -> dict[str, dict[str, float]]:
    run = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", *CONTAINERS],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=True,
    )
    rows = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
    result = {
        row["Name"]: {
            "cpu_percent": float(row["CPUPerc"].removesuffix("%")),
            "memory_mib": memory_mib(row["MemUsage"].split("/", 1)[0]),
        }
        for row in rows
    }
    if set(result) != set(CONTAINERS):
        raise ValueError("Both owned infrastructure containers must be measured")
    return result


class Infrastructure:
    """Sampled maxima, not kernel peak RSS; include sample counts/windows."""

    def __init__(self) -> None:
        self.samples: list[dict[str, Any]] = []
        self.started = time.perf_counter()
        self.finished = 0.0
        self.error: Exception | None = None

    async def sample(self) -> None:
        free = await asyncio.to_thread(available_mib)
        containers = await asyncio.to_thread(docker_sample)
        self.samples.append(
            {
                "elapsed_s": round(time.perf_counter() - self.started, 3),
                "free_mib": round(free, 2),
                "containers": containers,
            }
        )

    async def watch(self) -> None:
        try:
            while True:
                await asyncio.sleep(5)
                await self.sample()
        except Exception as error:
            # A missing metric invalidates evidence, but must not strand the
            # measured application or its fixture database lease.
            self.error = error

    def result(self) -> dict[str, Any]:
        if self.error is not None or len(self.samples) < 2:
            raise ValueError("Infrastructure resource window is incomplete") from self.error
        return {
            "sampling_interval_s": 5,
            "elapsed_s": round(self.finished - self.started, 3),
            "min_sampled_free_mib": min(s["free_mib"] for s in self.samples),
            "containers": {
                name: {
                    "sampled_peak_memory_mib": max(
                        s["containers"][name]["memory_mib"] for s in self.samples
                    ),
                    "sampled_peak_cpu_percent": max(
                        s["containers"][name]["cpu_percent"] for s in self.samples
                    ),
                }
                for name in CONTAINERS
            },
            "samples": self.samples,
        }
