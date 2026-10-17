"""No CSRF or session token in a URL (CP27 fix A1).

A token in a URL ends up in browser history, proxy and access logs and in
Referer headers. So:

- the photo upload carries its CSRF token as the FIRST field of its own
  multipart body (the gate reads that one small field and hands the rest of
  the stream to the handler; the file itself is never read by the gate);
- a `csrf` parameter in the query string of ANY studio request is refused,
  even with a correct token in the body;
- walking every studio screen and redirect, and the log lines written while
  doing so, finds neither the CSRF token nor the session cookie value.
"""

# ruff: noqa: F811  (the `world` fixture is imported by name)

from __future__ import annotations

import logging
import re
from typing import Any

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from tests.test_share_page_photos import phone_photo
from tests.test_studio_kinds import gift, yesno_form
from tests.test_studio_web import app_for, form, log_in, world  # noqa: F401  (fixture)

from gulbot.web import studio as studio_web

pytestmark = pytest.mark.infra


def upload(raw: bytes, csrf: str | None, *, csrf_first: bool = True) -> FormData:
    data = FormData()
    if csrf is not None and csrf_first:
        data.add_field("csrf", csrf)
    data.add_field("photo", raw, filename="photo.jpg", content_type="image/jpeg")
    if csrf is not None and not csrf_first:
        data.add_field("csrf", csrf)
    return data


async def _page(client: TestClient, csrf: str) -> int:
    made = await client.post("/studio/create", data=form(csrf), allow_redirects=False)
    assert made.status == 303
    return int(made.headers["Location"].rsplit("/", 1)[1])


async def test_the_upload_carries_its_token_in_the_body(world: dict[str, Any]) -> None:
    db = world["db"]
    await gift(db, world["a"], world["ca"])
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _page(client, csrf)
        screen = await (await client.get(f"/studio/page/{page_id}")).text()
        action = re.search(r'enctype="multipart/form-data" action="([^"]+)"', screen)
        assert action and "?" not in action.group(1), "the upload form's URL carries a query"
        first = re.search(
            r'enctype="multipart/form-data"[^>]*>\s*<input type="hidden" name="(\w+)"', screen
        )
        assert first and first.group(1) == "csrf", "the token must be the form's first field"
        sent = await client.post(
            f"/studio/page/{page_id}/photo",
            data=upload(phone_photo(400, 300), csrf),
            allow_redirects=False,
        )
        assert sent.status == 303, await sent.text()
    assert await db.scalar(text("SELECT count(*) FROM share_page_photos")) == 1


@pytest.mark.parametrize(
    "case", ["query_only", "query_and_body", "wrong", "missing", "not_first", "oversize"]
)
async def test_an_upload_without_its_body_token_is_refused(
    world: dict[str, Any], case: str
) -> None:
    db = world["db"]
    await gift(db, world["a"], world["ca"])
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _page(client, csrf)
        url = f"/studio/page/{page_id}/photo"
        raw = phone_photo(400, 300)
        body, query = {
            "query_only": (upload(raw, None), f"?csrf={csrf}"),
            "query_and_body": (upload(raw, csrf), f"?csrf={csrf}"),
            "wrong": (upload(raw, "x" * len(csrf)), ""),
            "missing": (upload(raw, None), ""),
            "not_first": (upload(raw, csrf, csrf_first=False), ""),
            "oversize": (upload(raw, csrf + "y" * 5000), ""),
        }[case]
        response = await client.post(url + query, data=body, allow_redirects=False)
        # A token in the URL is refused unread (400); a missing, wrong, late or
        # oversize body token fails the CSRF check (403).
        expected = 400 if case.startswith("query") else 403
        assert response.status == expected, (case, response.status)
    assert await db.scalar(text("SELECT count(*) FROM share_page_photos")) == 0


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/studio"), ("GET", "/studio/pages"), ("POST", "/studio/create")],
)
async def test_a_token_in_any_studio_url_is_refused(
    world: dict[str, Any], method: str, path: str
) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        response = await client.request(
            method,
            f"{path}?csrf={csrf}",
            data=form(csrf) if method == "POST" else None,
            allow_redirects=False,
        )
        assert response.status == 400, (method, path, response.status)
    assert await db.scalar(text("SELECT count(*) FROM share_pages")) == 0


async def test_no_url_redirect_or_log_line_carries_a_token(
    world: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    db = world["db"]
    await gift(db, world["a"], world["ca"])
    caplog.set_level(logging.DEBUG)
    bodies: list[str] = []
    locations: list[str] = []
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        session = client.session.cookie_jar.filter_cookies(client.make_url("/studio"))[
            studio_web.COOKIE
        ].value

        async def visit(method: str, path: str, data: Any = None) -> int | None:
            response = await client.request(method, path, data=data, allow_redirects=False)
            bodies.append(await response.text())
            if "Location" in response.headers:
                locations.append(response.headers["Location"])
                return (
                    int(response.headers["Location"].rsplit("/", 1)[1])
                    if "/done/" in response.headers["Location"]
                    else None
                )
            return None

        invite = await visit("POST", "/studio/create", form(csrf))
        yesno = await visit("POST", "/studio/create", yesno_form(csrf))
        for path in ("/studio", "/studio?kind=yesno", "/studio?kind=apology", "/studio/pages"):
            await visit("GET", path)
        for page_id in (invite, yesno):
            assert page_id is not None
            for path in (
                f"/studio/done/{page_id}",
                f"/studio/page/{page_id}",
                f"/studio/page/{page_id}/edit",
            ):
                await visit("GET", path)
            await visit(
                "POST", f"/studio/page/{page_id}/photo", upload(phone_photo(400, 300), csrf)
            )
        await visit("POST", "/studio/design", form(csrf, cat="all"))
        await visit("POST", "/studio/preview", form(csrf))
        await visit("POST", f"/studio/page/{invite}/edit", form(csrf, action="save"))
        await visit("POST", f"/studio/page/{invite}/delete", {"csrf": csrf})
        await visit("POST", f"/studio/page/{invite}/delete", {"csrf": csrf, "confirm": "1"})
        await visit("POST", "/studio/logout", {"csrf": csrf})
    urls = locations + [
        u for body in bodies for u in re.findall(r'(?:href|action|src|formaction)="([^"]*)"', body)
    ]
    assert urls, "the walk found no URLs at all"
    logs = "\n".join(record.getMessage() for record in caplog.records)
    for token in (csrf, session):
        assert not [u for u in urls if token in u], "a token in a URL"
        assert token not in logs, "a token in a log line"
