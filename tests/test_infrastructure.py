"""CP0 guards.

These exist so that a later well-meaning edit cannot quietly move this stack
onto the default ports, where it would collide with the other Postgres and
Redis already running on this machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import redis.asyncio as aioredis
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from gulbot.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def compose() -> dict:
    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_project_name_is_gulbot(compose: dict) -> None:
    assert compose["name"] == "gulbot"


@pytest.mark.parametrize(
    ("service", "expected"),
    [("postgres", "5433:5432"), ("redis", "6380:6379")],
)
def test_compose_publishes_non_default_ports(compose: dict, service: str, expected: str) -> None:
    assert compose["services"][service]["ports"] == [expected]


def test_settings_defaults_match_compose(settings: Settings, compose: dict) -> None:
    """Config and compose must not drift apart."""
    pg_host_port = int(compose["services"]["postgres"]["ports"][0].split(":")[0])
    redis_host_port = int(compose["services"]["redis"]["ports"][0].split(":")[0])
    assert settings.postgres_port == pg_host_port
    assert settings.redis_port == redis_host_port


def test_redis_logical_databases_are_distinct(settings: Settings) -> None:
    """A Celery purge must never be able to wipe live FSM state."""
    dbs = [
        settings.redis_db_broker,
        settings.redis_db_results,
        settings.redis_db_fsm,
        settings.redis_db_test,
    ]
    assert len(set(dbs)) == len(dbs)


def test_env_example_documents_every_setting(settings: Settings) -> None:
    """.env.example must stay in sync with Settings, or onboarding silently breaks."""
    text_ = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    documented = {
        line.split("=", 1)[0].strip().lower()
        for line in text_.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    missing = set(type(settings).model_fields) - documented
    assert not missing, f"undocumented settings: {sorted(missing)}"


@pytest.mark.infra
async def test_postgres_is_reachable(db: AsyncConnection) -> None:
    result = await db.execute(text("SELECT version()"))
    version = result.scalar_one()
    assert "PostgreSQL 16" in version, version


@pytest.mark.infra
async def test_redis_is_reachable(settings: Settings) -> None:
    client = aioredis.from_url(settings.redis_url(settings.redis_db_test))
    try:
        assert await client.ping() is True
    finally:
        await client.aclose()
