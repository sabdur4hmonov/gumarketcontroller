"""Where the pages live, as the bot hands them out.

PUBLIC_BASE_URL is an ORIGIN -- scheme, host, optional port, no path -- because
the pages refer to their own CSS and script from the root ("/static/...").

THE FEATURE IS OFF IN PRODUCTION UNTIL THE PAGES ARE ON HTTPS. A production bot
must never hand a customer an http:// link, nor a 127.0.0.1 one that only
works on the server; it says "coming soon" instead. Locally, any base URL
works, so everything can be built and tested before a domain exists.
"""

from __future__ import annotations

from gulbot.config import get_settings


def base_url() -> str:
    return get_settings().public_base_url.strip().rstrip("/")


def pages_available() -> bool:
    base = base_url()
    if not base.startswith(("http://", "https://")):
        return False
    return get_settings().environment != "production" or base.startswith("https://")


def page_url(token: str) -> str:
    return f"{base_url()}/p/{token}"


def gallery_url(kind: str, lang: str) -> str:
    return f"{base_url()}/demo/{kind}?lang={lang}"
