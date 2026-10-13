"""Plan collection cannot populate an unowned or large database."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from scripts.cp25_load import query_plans
from scripts.cp25_load.load_seed import OWNER_MARKER


@pytest.mark.parametrize("marker,shops", [("foreign", 10), (OWNER_MARKER, 51)])
async def test_explain_admission_rejects_before_fixture_writes(monkeypatch, marker, shops):
    conn = AsyncMock()
    conn.scalar.side_effect = [marker, shops]
    conn.execute.side_effect = AssertionError("Fixture writes before safe admission")
    context = AsyncMock()
    context.__aenter__.return_value = conn
    engine = SimpleNamespace(connect=MagicMock(return_value=context), dispose=AsyncMock())
    monkeypatch.setattr(query_plans, "create_async_engine", lambda *a, **k: engine)
    rejected = False
    try:
        await query_plans.capture()
    except RuntimeError:
        rejected = True
    assert rejected, "Plan collection must stop before touching unowned/large fixtures"
    assert conn.execute.await_count == 0, "No fixture insertion before ownership/size checks"
    assert engine.dispose.await_count == 1
