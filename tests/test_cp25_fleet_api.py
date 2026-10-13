"""Protocol checks on one/two fake shops; no capacity run or DB clients."""

from __future__ import annotations

import io
import json
import time
import unittest

import aiohttp
from PIL import Image
from scripts.cp25_load.fleet_api import FleetTelegram

TOKEN_A = "600001:CP25TEST" + "T" * 27
TOKEN_B = "600002:CP25TEST" + "T" * 27


class FleetProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.api = FleetTelegram(delay=0)
        await self.api.start()
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))

    async def asyncTearDown(self) -> None:
        await self.http.close()
        await self.api.close()

    async def call(self, token: str, method: str, data: dict) -> tuple[int, dict]:
        async with self.http.post(self.api.base_url + f"/bot{token}/{method}", json=data) as reply:
            return reply.status, await reply.json()

    async def test_idle_poll_honours_telegram_timeout(self) -> None:
        started = time.perf_counter()
        status, body = await self.call(TOKEN_A, "getUpdates", {"timeout": 2})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"], [])
        self.assertGreaterEqual(time.perf_counter() - started, 1.8)

    async def test_one_unauthorized_shop_does_not_fail_another(self) -> None:
        async with self.http.post(
            self.api.base_url + "/control/fault",
            json={"bot_id": 600001, "mode": "unauthorized"},
        ) as reply:
            self.assertEqual(reply.status, 200)
        status_a, body_a = await self.call(TOKEN_A, "getMe", {})
        status_b, body_b = await self.call(TOKEN_B, "getMe", {})
        self.assertEqual((status_a, body_a["error_code"]), (401, 401))
        self.assertEqual((status_b, body_b["result"]["id"]), (200, 600002))

    async def test_updates_remain_until_offset_acknowledges_them(self) -> None:
        async with self.http.post(
            self.api.base_url + "/control/updates",
            json={"updates": [{"bot_id": 600001, "update": {"update_id": 1}}]},
        ) as reply:
            self.assertEqual(reply.status, 200)
        _, first = await self.call(TOKEN_A, "getUpdates", {"offset": 0, "timeout": 0})
        _, again = await self.call(TOKEN_A, "getUpdates", {"offset": 0, "timeout": 0})
        _, acked = await self.call(TOKEN_A, "getUpdates", {"offset": 2, "timeout": 0})
        self.assertEqual(first["result"], [{"update_id": 1}])
        self.assertEqual(again["result"], first["result"])
        self.assertEqual(acked["result"], [])

    async def test_media_group_counts_real_uploaded_bytes_once(self) -> None:
        form = aiohttp.FormData()
        form.add_field("chat_id", "-1001000001")
        form.add_field(
            "media",
            json.dumps(
                [
                    {"type": "photo", "media": "attach://a"},
                    {"type": "photo", "media": "attach://b"},
                ]
            ),
        )
        form.add_field("a", b"first", filename="a.jpg", content_type="image/jpeg")
        form.add_field("b", b"second", filename="b.jpg", content_type="image/jpeg")
        async with self.http.post(
            self.api.base_url + f"/bot{TOKEN_A}/sendMediaGroup",
            data=form,
        ) as reply:
            self.assertEqual(reply.status, 200)
            body = await reply.json()
        self.assertEqual(self.api.uploads, 2)
        self.assertEqual(self.api.upload_bytes, 11)
        self.assertTrue(
            all(item["photo"][0]["file_id"].startswith("cp25-upload-") for item in body["result"])
        )

    async def test_missing_media_attachment_is_refused(self) -> None:
        status, body = await self.call(
            TOKEN_A,
            "sendMediaGroup",
            {
                "chat_id": "-1001000001",
                "media": [{"type": "photo", "media": "attach://missing"}],
            },
        )
        self.assertEqual((status, body.get("error_code")), (400, 400))

    async def test_default_download_fixture_is_a_real_original_photo(self) -> None:
        async with self.http.get(
            self.api.base_url + f"/file/bot{TOKEN_A}/photos/cp25.jpg"
        ) as reply:
            self.assertEqual(reply.status, 200)
            raw = await reply.read()
        self.assertTrue(
            raw, "a download fixture must not conceal image-path failures with empty bytes"
        )
        with Image.open(io.BytesIO(raw)) as photo:
            photo.load()
            self.assertEqual(photo.size, (32, 24))
            self.assertEqual(photo.format, "JPEG")

    async def test_reply_only_flood_does_not_fake_a_polling_failure(self) -> None:
        async with self.http.post(
            self.api.base_url + "/control/fault",
            json={"bot_id": 600001, "mode": "flood", "methods": ["sendMessage"]},
        ) as reply:
            self.assertEqual(reply.status, 200)
        me_status, _ = await self.call(TOKEN_A, "getMe", {})
        poll_status, _ = await self.call(TOKEN_A, "getUpdates", {"timeout": 0})
        bad_status, refusal = await self.call(
            TOKEN_A, "sendMessage", {"chat_id": 1, "text": "test"}
        )
        good_status, _ = await self.call(TOKEN_B, "sendMessage", {"chat_id": 1, "text": "test"})
        self.assertEqual((me_status, poll_status), (200, 200))
        self.assertEqual((bad_status, refusal["parameters"]["retry_after"]), (429, 1))
        self.assertEqual(good_status, 200)


if __name__ == "__main__":
    unittest.main()
