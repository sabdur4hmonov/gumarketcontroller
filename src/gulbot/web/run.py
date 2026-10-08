"""The page server's entrypoint.

    python -m gulbot.web.run

Serves on WEB_HOST:WEB_PORT (default 127.0.0.1:8088). In production it sits
behind a TLS-terminating reverse proxy that answers for PUBLIC_BASE_URL; see
docs/DEPLOY.md, "Public pages".

NO ACCESS LOG. Every page's address is its secret, and an access log would
write every one of them to disk in the clear. Errors are still logged, without
the path's token.
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from gulbot.config import get_settings
from gulbot.db.session import build_session_factory
from gulbot.services import admin_auth
from gulbot.web.app import build_app

log = logging.getLogger("gulbot.web")


async def queue_notification(page_id: int, delay: float = 0) -> None:
    """Hand the creator's message to the worker -- now, or `delay` seconds
    from now (the "nothing chosen yet" check). Sending is a Telegram call,
    which does not belong in a web request."""
    from gulbot.worker.tasks import notify_page_answer

    await asyncio.to_thread(
        notify_page_answer.apply_async, args=(page_id,), countdown=max(0, int(delay))
    )


async def main() -> None:
    settings = get_settings()  # the production guard runs here, first
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)-5s %(name)s %(message)s"
    )
    app = build_app(
        session_factory=build_session_factory(),
        notify=queue_notification,
        public_base_url=settings.public_base_url,
        trust_proxy=settings.web_trust_proxy,
        admin_ids=admin_auth.admin_ids,
    )
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, settings.web_host, settings.web_port)
    await site.start()
    log.info(
        "pages: serving on %s:%s for %s (environment=%s)",
        settings.web_host,
        settings.web_port,
        settings.public_base_url,
        settings.environment,
    )
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
