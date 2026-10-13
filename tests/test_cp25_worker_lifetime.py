"""Task lifecycle guard with fake bodies, no DB/Redis/Telegram operations."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch


class WorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_exercises_public_task_bodies_on_distinct_closed_loops(self) -> None:
        from scripts.cp25_load.load_roles import worker_role

        import gulbot.worker.tasks as tasks

        calls: Counter[str] = Counter()
        loops: list[asyncio.AbstractEventLoop] = []

        async def pulse() -> dict[str, int]:
            loops.append(asyncio.get_running_loop())
            return {"sent": 2, "groups": 2, "claimed": 2}

        def reminder() -> dict[str, int]:
            calls["reminder"] += 1
            return asyncio.run(pulse())

        def ping() -> dict[str, int]:
            calls["ping"] += 1
            return asyncio.run(pulse())

        with (
            tempfile.TemporaryDirectory(prefix="cp25-worker-unit-") as temporary,
            patch.object(tasks, "_send_due_reminders", pulse),
            patch.object(tasks, "_send_order_pings", pulse),
            patch.object(tasks.send_due_reminders, "run", reminder),
            patch.object(tasks.send_order_pings, "run", ping),
        ):
            await worker_role("http://127.0.0.1:1", Path(temporary), 2)
        self.assertEqual(calls, {"reminder": 1, "ping": 1})
        self.assertEqual(len({id(loop) for loop in loops}), 2)
        self.assertTrue(all(loop.is_closed() for loop in loops))


if __name__ == "__main__":
    unittest.main()
