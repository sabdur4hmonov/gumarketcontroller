"""Capacity coordinator guard tests; no children or benchmarks are launched."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.cp25_load import capacity


class CoordinatorMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_readiness_does_not_bypass_ram_floor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cp25-memory-unit-") as temporary:
            path = Path(temporary) / "ready.json"
            path.write_text('{"ready": true}', encoding="utf-8")
            child = Mock()
            child.poll.return_value = None
            with (
                patch.object(capacity, "available_mib", return_value=128),
                self.assertRaisesRegex(RuntimeError, "RAM"),
            ):
                await capacity.wait_file(path, child, seconds=0.1)

    async def test_readiness_is_accepted_with_headroom(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cp25-memory-unit-") as temporary:
            path = Path(temporary) / "ready.json"
            path.write_text('{"ready": true}', encoding="utf-8")
            child = Mock()
            child.poll.return_value = None
            with patch.object(capacity, "available_mib", return_value=2048):
                self.assertEqual(await capacity.wait_file(path, child), {"ready": True})


if __name__ == "__main__":
    unittest.main()
