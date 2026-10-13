"""Global event-loop lag; deliberately never guesses a responsible shop."""

from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("gulbot.loop")


class LagMeter:
    def __init__(self, now: float, *, interval: float = 0.05, threshold: float = 0.1) -> None:
        self.interval = interval
        self.threshold = threshold
        self.expected = now + interval

    def observe(self, now: float) -> float | None:
        lag = max(0.0, now - self.expected)
        self.expected = now + self.interval
        return lag if lag > self.threshold else None


async def monitor() -> None:
    loop = asyncio.get_running_loop()
    meter = LagMeter(loop.time())
    while True:
        await asyncio.sleep(meter.interval)
        lag = meter.observe(loop.time())
        if lag is not None:
            log.warning(json.dumps({"event": "event_loop_block", "lag_ms": round(lag * 1000, 2)}))
