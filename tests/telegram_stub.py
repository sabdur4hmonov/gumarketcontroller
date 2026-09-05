"""A fake Telegram Bot API, served over real HTTP on localhost.

WHY A REAL SERVER AND NOT A MOCK. The thing under test is whether an
`aiohttp.ClientSession` is reused across event loops. A mocked session proves
nothing about that, because the loop binding lives in aiohttp's connector --
precisely the part a mock replaces. So the send has to be a genuine HTTP
request through aiogram's real `AiohttpSession`.

It runs on a THREAD with the stdlib's `ThreadingHTTPServer`, deliberately: an
`aiohttp.web` server would be bound to one event loop and die with it, which is
exactly the property these tests exist to exercise in the client.

No network leaves the machine, and no real bot token is involved -- the tests
build the bot with `bot_harness.TEST_TOKEN`.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType


class _Handler(BaseHTTPRequestHandler):
    server: FakeTelegram  # type: ignore[assignment]

    def _respond(self) -> None:
        # ONLY the method name is kept. The path also contains the bot token,
        # and a recorded token ends up in assertion output and CI logs.
        method = self.path.rsplit("/", 1)[-1]
        self.server.calls.append(method)

        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

        body = json.dumps(
            {
                "ok": True,
                "result": {
                    "message_id": len(self.server.calls),
                    "date": int(datetime.now(tz=UTC).timestamp()),
                    "chat": {"id": 1, "type": "private"},
                    "text": "ok",
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _respond
    do_POST = _respond

    def log_message(self, format: str, *args: object) -> None:
        """Silence. The default handler prints the request line, token included."""
        return None


class FakeTelegram(ThreadingHTTPServer):
    """Context manager: `with FakeTelegram() as api:` gives `api.base_url`."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.calls: list[str] = []
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server_address[0], self.server_address[1]
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeTelegram:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5)
