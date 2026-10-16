"""DEV_UNLIMITED_PAGES: a local-testing switch that lifts the share-page limits.

On, and only outside production, it bypasses the creation limits
(services/share_pages.check_limits), the premium gate (services/premium.unlocked)
and the public pages' rate limits (web/app.limit) -- all through ONE helper,
gulbot.config.unlimited_pages_active. Off, nothing changes. In production the
startup guard refuses it, and the helper says False even if asked directly.

The panels' login limits (admin_login, shop_login) are never bypassed.

MUTATION PROOF (2026-10-16): dropping the environment check from
unlimited_pages_active (returning `settings.dev_unlimited_pages` alone) fails
test_production_never_bypasses_even_if_asked_directly; reverted.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory
from tests.test_share_pages_service import create, invite, make_customer, make_shop, yesno

from gulbot import config
from gulbot.config import Settings, production_config_problems, unlimited_pages_active
from gulbot.models.premium import PremiumUnlock
from gulbot.services import premium, share_pages
from gulbot.services.share_pages import PageLimitReached
from gulbot.web import app as web_app
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra

JSON_HEADERS = {"X-Requested-With": "gulbot", "Content-Type": "application/json"}


def _switch(monkeypatch: pytest.MonkeyPatch, *, on: bool, environment: str = "local") -> Settings:
    """What every process would read, with the flag and environment chosen."""
    chosen = config.get_settings().model_copy(
        update={"dev_unlimited_pages": on, "environment": environment}
    )
    monkeypatch.setattr(config, "get_settings", lambda: chosen)
    return chosen


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


@pytest.fixture
async def client(db: AsyncConnection) -> AsyncIterator[TestClient]:
    async def notify(page_id: int, delay: float = 0) -> None:
        return None

    app = build_app(
        session_factory=bound_session_factory(db),
        notify=notify,
        public_base_url="http://127.0.0.1:8088",
        yes_limit=2,
    )
    async with TestClient(TestServer(app)) as test_client:
        yield test_client


async def _yes_statuses(
    db: AsyncConnection, session: AsyncSession, client: TestClient
) -> list[int]:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 711)
    page = await create(session, shop, customer, yesno(notify_creator=False))
    await session.commit()
    return [
        (await client.post(f"/p/{page.token}/yes", data="{}", headers=JSON_HEADERS)).status
        for _ in range(4)
    ]


def test_the_suite_runs_with_the_switch_off() -> None:
    """conftest pins it, so a developer's .env cannot loosen the other tests."""
    assert config.get_settings().dev_unlimited_pages is False
    assert unlimited_pages_active() is False


# --- off: every limit as before --------------------------------------------------


async def test_off_the_daily_limit_holds(
    db: AsyncConnection, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch(monkeypatch, on=False)
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 701)
    for _ in range(share_pages.CREATE_PER_DAY):
        await create(session, shop, customer, yesno())
    with pytest.raises(PageLimitReached) as limit:
        await create(session, shop, customer, yesno())
    assert limit.value.which == "daily"


async def test_off_the_live_limit_holds(
    db: AsyncConnection, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch(monkeypatch, on=False)
    monkeypatch.setattr(share_pages, "CREATE_PER_DAY", 1000)
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 702)
    for _ in range(share_pages.LIVE_PER_CUSTOMER):
        await create(session, shop, customer, yesno())
    with pytest.raises(PageLimitReached) as limit:
        await create(session, shop, customer, yesno())
    assert limit.value.which == "live"


async def test_off_premium_stays_locked(
    db: AsyncConnection, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch(monkeypatch, on=False)
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 703)
    with pytest.raises(premium.PremiumLocked):
        await create(session, shop, customer, invite(template="deco"))


async def test_off_the_web_limiter_answers_429(
    db: AsyncConnection,
    session: AsyncSession,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _switch(monkeypatch, on=False)
    assert await _yes_statuses(db, session, client) == [200, 200, 429, 429]


# --- on, locally: all four lifted ------------------------------------------------


async def test_on_locally_both_creation_limits_are_lifted(
    db: AsyncConnection, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch(monkeypatch, on=True)
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 704)
    # Past CREATE_PER_DAY and past LIVE_PER_CUSTOMER, all inside one day.
    for _ in range(share_pages.LIVE_PER_CUSTOMER + 1):
        await create(session, shop, customer, yesno())


async def test_on_locally_premium_is_open_and_nothing_is_written(
    db: AsyncConnection, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch(monkeypatch, on=True)
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 705)
    page = await create(session, shop, customer, invite(template="deco"))
    assert page.template == "deco"
    unlocks = await session.scalar(
        select(func.count()).select_from(PremiumUnlock).where(PremiumUnlock.shop_id == shop)
    )
    assert unlocks == 0


async def test_on_locally_the_web_limiter_lets_everything_through(
    db: AsyncConnection,
    session: AsyncSession,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _switch(monkeypatch, on=True)
    assert await _yes_statuses(db, session, client) == [200, 200, 200, 200]


async def test_on_locally_the_login_limits_still_hold(
    db: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _switch(monkeypatch, on=True)

    async def notify(page_id: int, delay: float = 0) -> None:
        return None

    app = build_app(
        session_factory=bound_session_factory(db),
        notify=notify,
        public_base_url="http://127.0.0.1:8088",
        admin_login_limit=1,
    )
    for bucket in sorted(web_app.LOGIN_BUCKETS):
        request = make_mocked_request("POST", "/admin/login", app=app)
        web_app.limit(request, bucket)
        with pytest.raises(web.HTTPTooManyRequests):
            web_app.limit(request, bucket)


# --- production: refused, and never active ----------------------------------------


def test_production_refuses_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    chosen = _switch(monkeypatch, on=True, environment="production")
    problems = production_config_problems(chosen, environ={})
    assert any(problem.startswith("DEV_UNLIMITED_PAGES is on") for problem in problems)
    off = chosen.model_copy(update={"dev_unlimited_pages": False})
    assert not any(
        "DEV_UNLIMITED_PAGES" in problem for problem in production_config_problems(off, environ={})
    )


async def test_production_never_bypasses_even_if_asked_directly(
    db: AsyncConnection, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen = _switch(monkeypatch, on=True, environment=" Production")
    assert unlimited_pages_active(chosen) is False
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 706)
    assert await premium.unlocked(session, shop_id=shop, customer_id=customer) is False
