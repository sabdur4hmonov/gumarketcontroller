"""CP27.1b: the design picker is its own studio screen, not forty cards inline.

The form shows the chosen design as ONE card with "O'zgartirish". That button
opens /studio/design, which carries everything typed so far in hidden fields,
filters by category (to'y / tug'ilgan kun / boshqa) and by free/premium, and
sends the creator back to the same form with the new design and nothing lost.
Locked designs can be looked at, never chosen. No JavaScript is involved.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from tests.test_studio_web import app_for, form, log_in, world  # noqa: F401  (fixture)

from gulbot.services import premium
from gulbot.web import render
from gulbot.web.studio_designs import CATEGORIES, DESIGN_CATEGORIES, category_for_event

pytestmark = pytest.mark.infra


def cards(body: str) -> list[str]:
    """The design keys a picker screen offers, in order."""
    return re.findall(r'data-design="([a-z]+)"', body)


def test_every_design_has_a_category() -> None:
    assert set(DESIGN_CATEGORIES) == set(render.THEME_NAMES)
    for key, cats in DESIGN_CATEGORIES.items():
        assert cats and cats <= set(CATEGORIES), key


def test_an_event_opens_the_picker_on_its_own_category() -> None:
    assert category_for_event("wedding") == "toy"
    assert category_for_event("birthday") == "tugilgan"
    assert category_for_event("corporate") == "boshqa"


async def test_the_form_shows_one_chosen_design_not_forty(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        await log_in(client, db, world["a"], world["ca"])
        body = await (await client.get("/studio")).text()
    assert cards(body) == ["milliy"], "the form must carry one design card"
    assert 'name="template" value="milliy"' in body
    assert "O‘zgartirish" in body and 'formaction="/studio/design"' in body


async def test_the_picker_keeps_what_was_typed_and_filters(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        data = form(csrf, action="pick", name_1="Zarina", venue_name_2="Kelin tomon")
        opened = await client.post("/studio/design", data=data)
        body = await opened.text()
        assert opened.status == 200
        # A wedding opens on wedding designs; what was typed rides along.
        assert set(cards(body)) == {k for k, c in DESIGN_CATEGORIES.items() if "toy" in c}
        assert 'type="hidden" name="name_1" value="Zarina"' in body
        assert 'type="hidden" name="venue_name_2" value="Kelin tomon"' in body

        everything = await (await client.post("/studio/design", data={**data, "cat": "all"})).text()
        assert sorted(cards(everything)) == sorted(render.THEME_NAMES)

        free = await (
            await client.post("/studio/design", data={**data, "cat": "all", "tier": "free"})
        ).text()
        assert cards(free) and not any(premium.is_premium_template(k) for k in cards(free))

        birthday = await (
            await client.post("/studio/design", data={**data, "cat": "tugilgan"})
        ).text()
        assert set(cards(birthday)) == {k for k, c in DESIGN_CATEGORIES.items() if "tugilgan" in c}


async def test_choosing_returns_to_the_same_form_with_nothing_lost(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        data = form(csrf, name_1="Zarina", venue_name_2="Kelin tomon")
        back = await (await client.post("/studio/design", data={**data, "choose": "tungi"})).text()
        assert cards(back) == ["tungi"]
        assert 'name="template" value="tungi"' in back
        assert 'value="Zarina"' in back and 'value="Kelin tomon"' in back
        made = await client.post(
            "/studio/create", data={**data, "template": "tungi"}, allow_redirects=False
        )
        assert made.status == 303
    assert await db.scalar(text("SELECT template FROM share_pages")) == "tungi"


async def test_a_locked_design_can_be_looked_at_but_not_chosen(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        data = form(csrf)
        picker = await (await client.post("/studio/design", data={**data, "cat": "all"})).text()
        assert re.search(r'name="choose" value="milliy"', picker)
        assert not re.search(r'name="choose" value="deco"', picker), (
            "a locked card offers no choice"
        )
        assert re.search(r'name="preview_template" value="deco"', picker)
        forced = await client.post("/studio/design", data={**data, "choose": "deco"})
        body = await forced.text()
        assert forced.status == 422 and 'name="template" value="deco"' not in body


async def test_an_unknown_design_or_filter_is_refused(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        data = form(csrf)
        assert (await client.post("/studio/design", data={**data, "choose": "nope"})).status == 422
        odd = await client.post("/studio/design", data={**data, "cat": "<x>", "tier": "<y>"})
        assert odd.status == 200 and "<x>" not in await odd.text()
