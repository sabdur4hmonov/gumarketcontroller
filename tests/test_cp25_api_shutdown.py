"""Snapshot completion guard, without starting an HTTP server or a load job."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ApiShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_resource_report_is_published_after_api_close(self) -> None:
        from scripts.cp25_load import fleet_api

        class FakeApi:
            base_url = "http://127.0.0.1:1"
            closed = False

            async def start(self) -> None:
                pass

            async def close(self) -> None:
                self.closed = True

        api = FakeApi()

        class FakeResources:
            def result(self) -> dict[str, bool]:
                return {"api_closed": api.closed}

        with (
            tempfile.TemporaryDirectory(prefix="cp25-api-unit-") as temporary,
            patch.object(fleet_api, "FleetTelegram", return_value=api),
            patch.object(fleet_api, "Resources", FakeResources),
        ):
            output = Path(temporary)
            (output / "stop-api").touch()
            await fleet_api.api_role(output)
            report = json.loads((output / "api-resources.json").read_text(encoding="utf-8"))
        self.assertTrue(
            report["api_closed"], "an incomplete shutdown is not a finished resource report"
        )


if __name__ == "__main__":
    unittest.main()
