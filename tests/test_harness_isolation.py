"""Prove the rollback fixture actually isolates tests.

These two tests are ordered and coupled on purpose: the first writes, the
second asserts the write is gone. If the fixture ever stops rolling back,
this fails instead of silently letting tests pollute each other.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

TABLE = "harness_isolation_probe"


@pytest.mark.infra
async def test_a_writes_a_row(db: AsyncConnection) -> None:
    await db.execute(text(f"CREATE TABLE {TABLE} (id int primary key)"))
    await db.execute(text(f"INSERT INTO {TABLE} (id) VALUES (1)"))
    count = (await db.execute(text(f"SELECT count(*) FROM {TABLE}"))).scalar_one()
    assert count == 1


@pytest.mark.infra
async def test_b_sees_no_trace_of_it(db: AsyncConnection) -> None:
    exists = (await db.execute(text("SELECT to_regclass(:t)"), {"t": TABLE})).scalar_one()
    assert exists is None, "previous test leaked into this one: rollback is broken"
