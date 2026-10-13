"""Measure actual application queries and physical pool connections."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from .resources import percentile


class DbMeter:
    def __init__(self, engine: AsyncEngine) -> None:
        self.times_ms: list[float] = []
        self.connections: set[int] = set()
        self.peak_connections = 0
        self.checked_out = 0
        self.peak_checked_out = 0
        for name, callback in (
            ("before_cursor_execute", self.before),
            ("after_cursor_execute", self.after),
            ("connect", self.connect),
            ("close", self.close),
            ("checkout", self.checkout),
            ("checkin", self.checkin),
        ):
            event.listen(engine.sync_engine, name, callback)

    def before(
        self,
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        many: bool,
    ) -> None:
        context.cp25_started = time.perf_counter()

    def after(
        self,
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        many: bool,
    ) -> None:
        self.times_ms.append((time.perf_counter() - context.cp25_started) * 1000)

    def connect(self, connection: Any, record: Any) -> None:
        self.connections.add(id(record))
        self.peak_connections = max(self.peak_connections, len(self.connections))

    def close(self, connection: Any, record: Any) -> None:
        self.connections.discard(id(record))

    def checkout(self, connection: Any, record: Any, proxy: Any) -> None:
        self.checked_out += 1
        self.peak_checked_out = max(self.peak_checked_out, self.checked_out)

    def checkin(self, connection: Any, record: Any) -> None:
        self.checked_out -= 1

    def result(self) -> dict[str, Any]:
        return {
            "queries": len(self.times_ms),
            "query_total_ms": round(sum(self.times_ms), 2),
            "query_p50_ms": percentile(self.times_ms, 50),
            "query_p95_ms": percentile(self.times_ms, 95),
            "query_p99_ms": percentile(self.times_ms, 99),
            "peak_connections": self.peak_connections,
            "peak_checked_out": self.peak_checked_out,
        }
