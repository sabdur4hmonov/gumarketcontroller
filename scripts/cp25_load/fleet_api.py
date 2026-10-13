"""Fleet-scale localhost Telegram API stub (CP25 preparation, not yet integrated).

Keeps real HTTP and per-bot long polls without a native thread per socket.
Only synthetic bot IDs and method counts are retained; tokens are never logged.
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from aiohttp import web

from .resources import Resources, atomic_json


def original_fixture_photo() -> bytes:
    """A tiny authored colour sample, never a customer's or a remote photo."""
    from PIL import Image

    with Image.new("RGB", (32, 24), (35, 82, 57)) as photo:
        output = io.BytesIO()
        photo.save(output, format="JPEG", quality=80)
    return output.getvalue()


class FleetTelegram:
    def __init__(self, *, delay: float = 0.005, photo: bytes = b"") -> None:
        self.delay = delay
        self.photo = photo
        self.updates: dict[int, deque[dict[str, Any]]] = defaultdict(deque)
        self.wake: dict[int, asyncio.Event] = defaultdict(asyncio.Event)
        self.faults: dict[int, str] = {}
        self.fault_methods: dict[int, frozenset[str] | None] = {}
        self.calls: Counter[str] = Counter()
        self.replies: list[dict[str, Any]] = []
        self.polls = 0
        self.peak_polls = 0
        self.polled_bot_ids: set[int] = set()
        self.uploads = 0
        self.upload_bytes = 0
        self.next_message = 0
        self.app = web.Application(client_max_size=12 * 1024 * 1024)
        self.app.router.add_post("/bot{token}/{method}", self.request)
        self.app.router.add_get("/file/bot{token}/{path:.*}", self.file)
        self.app.router.add_post("/control/updates", self.enqueue)
        self.app.router.add_post("/control/fault", self.fault)
        self.app.router.add_get("/control/stats", self.stats)
        self.runner: web.AppRunner | None = None
        self.base_url = ""

    async def start(self) -> None:
        if not self.photo:
            self.photo = await asyncio.to_thread(original_fixture_photo)
        self.runner = web.AppRunner(
            self.app, access_log=None, handler_cancellation=True, shutdown_timeout=5
        )
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        assert self.runner.addresses
        self.base_url = f"http://127.0.0.1:{self.runner.addresses[0][1]}"

    async def close(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()

    async def enqueue(self, request: web.Request) -> web.Response:
        body = await request.json()
        for item in body["updates"]:
            bot_id = int(item["bot_id"])
            update = item["update"]
            self.updates[bot_id].append(update)
            self.wake[bot_id].set()
        return web.json_response({"queued": len(body["updates"])})

    async def fault(self, request: web.Request) -> web.Response:
        body = await request.json()
        bot_id = int(body["bot_id"])
        self.faults[bot_id] = body["mode"]
        self.fault_methods[bot_id] = frozenset(body["methods"]) if "methods" in body else None
        self.wake[bot_id].set()
        return web.json_response({"ok": True})

    async def stats(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "calls": dict(self.calls),
                "replies": self.replies,
                "polls": self.polls,
                "peak_polls": self.peak_polls,
                "polled_shops": len(self.polled_bot_ids),
                "uploads": self.uploads,
                "upload_bytes": self.upload_bytes,
            }
        )

    async def file(self, request: web.Request) -> web.Response:
        return web.Response(body=self.photo, content_type="image/jpeg")

    def message(
        self, bot_id: int, data: Any, *, photo: bool = False, method: str | None = None
    ) -> dict[str, Any]:
        self.next_message += 1
        chat_id = int(data.get("chat_id", 1))
        result: dict[str, Any] = {
            "message_id": self.next_message,
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "channel" if chat_id < 0 else "private"},
            "from": {"id": bot_id, "is_bot": True, "first_name": "CP25 fake"},
        }
        if photo:
            media = data.get("photo", "cp25-photo")
            result["photo"] = [
                {
                    "file_id": str(media),
                    "file_unique_id": str(media),
                    "width": 32,
                    "height": 24,
                    "file_size": len(self.photo),
                }
            ]
            result["caption"] = str(data.get("caption", ""))
        else:
            result["text"] = str(data.get("text", ""))
        self.replies.append(
            {
                "bot_id": bot_id,
                "chat_id": chat_id,
                "method": method or ("sendPhoto" if photo else "sendMessage"),
                "received_ns": time.perf_counter_ns(),
                "role": "customer"
                if "CP25 customer" in result.get("text", "")
                else ("owner" if result.get("text", "").startswith("Joylandi: ") else "other"),
            }
        )
        return result

    async def request(self, request: web.Request) -> web.Response:
        bot_id = int(request.match_info["token"].split(":", 1)[0])
        method = request.match_info["method"]
        data: dict[str, Any] = (
            await request.json()
            if request.content_type == "application/json"
            else dict(await request.post())
        )
        # Count transferred multipart fields once, including media groups.
        # Request-owned temporary files must not be read on the API loop.
        uploads: dict[str, str] = {}
        for name, value in data.items():
            if isinstance(value, web.FileField):
                raw = await asyncio.to_thread(value.file.read)
                self.uploads += 1
                self.upload_bytes += len(raw)
                uploads[name] = f"cp25-upload-{bot_id}-{self.uploads}"
        data.update(uploads)
        self.calls[method] += 1
        fault = self.faults.get(bot_id)
        methods = self.fault_methods.get(bot_id)
        if methods is not None and method not in methods:
            fault = None
        if fault == "unauthorized":
            return web.json_response(
                {"ok": False, "error_code": 401, "description": "Unauthorized"}, status=401
            )
        if fault == "flood":
            return web.json_response(
                {
                    "ok": False,
                    "error_code": 429,
                    "description": "Retry later",
                    "parameters": {"retry_after": 1},
                },
                status=429,
            )
        if fault == "network":
            return web.Response(status=503, text="fake outage")
        if fault == "stall":
            await asyncio.sleep(120)
        await asyncio.sleep(self.delay)
        if method == "getMe":
            result: Any = {
                "id": bot_id,
                "is_bot": True,
                "first_name": "CP25 fake",
                "username": f"cp25_{bot_id}_bot",
            }
        elif method == "getUpdates":
            self.polled_bot_ids.add(bot_id)
            self.polls += 1
            self.peak_polls = max(self.peak_polls, self.polls)
            try:
                offset = int(data.get("offset", 0))
                queue = self.updates[bot_id]
                while queue and queue[0]["update_id"] < offset:
                    queue.popleft()
                if not queue:
                    self.wake[bot_id].clear()
                    try:
                        # Honour the real client's idle long-poll duration.
                        # Returning every second would inflate idle RPC/CPU
                        # and turn the baseline into a different workload.
                        async with asyncio.timeout(min(float(data.get("timeout", 1)), 30)):
                            await self.wake[bot_id].wait()
                    except TimeoutError:
                        pass
                result = list(queue)[:100]
            finally:
                self.polls -= 1
        elif method == "getFile":
            result = {
                "file_id": str(data["file_id"]),
                "file_unique_id": "cp25-photo",
                "file_size": len(self.photo),
                "file_path": "photos/cp25.jpg",
            }
        elif method in {"sendMessage", "sendPhoto"}:
            result = self.message(bot_id, data, photo=method == "sendPhoto")
        elif method == "sendMediaGroup":
            media = data["media"]
            items = json.loads(media) if isinstance(media, str) else media
            resolved = []
            for item in items:
                file_id = item["media"]
                if file_id.startswith("attach://"):
                    name = file_id.removeprefix("attach://")
                    if name not in uploads:
                        return web.json_response(
                            {"ok": False, "error_code": 400, "description": "Missing attachment"},
                            status=400,
                        )
                    file_id = uploads[name]
                resolved.append({**item, "media": file_id})
            result = [
                self.message(
                    bot_id,
                    {**data, "photo": item["media"], "caption": item.get("caption", "")},
                    photo=True,
                )
                for item in resolved
            ]
        elif method.startswith("editMessage"):
            result = self.message(bot_id, data, photo=method == "editMessageMedia", method=method)
        elif method == "getChat":
            result = {"id": int(data["chat_id"]), "type": "channel", "title": "CP25 fake"}
        elif method == "getChatMember":
            result = {
                "status": "administrator",
                "user": {"id": bot_id, "is_bot": True, "first_name": "CP25 fake"},
                "can_be_edited": True,
                "is_anonymous": False,
                "can_manage_chat": True,
                "can_delete_messages": True,
                "can_manage_video_chats": True,
                "can_restrict_members": True,
                "can_promote_members": True,
                "can_change_info": True,
                "can_invite_users": True,
                "can_post_stories": True,
                "can_edit_stories": True,
                "can_delete_stories": True,
                "can_post_messages": True,
            }
        elif method in {
            "answerCallbackQuery",
            "deleteMessage",
            "setMyCommands",
            "deleteWebhook",
            "setWebhook",
        }:
            result = True
        else:
            return web.json_response(
                {
                    "ok": False,
                    "error_code": 400,
                    "description": f"Unsupported fake method: {method}",
                },
                status=400,
            )
        return web.json_response({"ok": True, "result": result})


async def api_role(output: Path) -> None:
    resources = Resources()
    api = FleetTelegram()
    await api.start()
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(atomic_json, output / "api-ready.json", {"url": api.base_url})
    try:
        while not await asyncio.to_thread((output / "stop-api").exists):
            resources.sample()
            await asyncio.sleep(0.1)
    finally:
        await api.close()
        await asyncio.to_thread(atomic_json, output / "api-resources.json", resources.result())
