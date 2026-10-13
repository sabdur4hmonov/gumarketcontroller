"""An owned one-shot marker crashes only the selected synthetic poller."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import GetUpdates
from scripts.cp25_load.load_roles import install_local_api


async def test_crash_is_one_shot_and_only_the_bad_shop(monkeypatch, tmp_path) -> None:
    marker = tmp_path / "crash"
    marker.touch()
    monkeypatch.setenv("CP25_CRASH_FILE", str(marker))
    monkeypatch.setattr(AiohttpSession, "make_request", AsyncMock(return_value=[]))
    restore = install_local_api("http://127.0.0.1:1")
    session = SimpleNamespace(api=None)
    good = SimpleNamespace(id=600002, token="600002:CP25TEST" + "T" * 27)
    bad = SimpleNamespace(id=600001, token="600001:CP25TEST" + "T" * 27)
    crashed = False
    try:
        assert await AiohttpSession.make_request(session, good, GetUpdates()) == []
        try:
            await AiohttpSession.make_request(session, bad, GetUpdates())
        except asyncio.CancelledError:
            crashed = True
        assert crashed, "The synthetic poller crash must actually happen"
        assert not marker.exists(), "Only one crash is injected"
        assert await AiohttpSession.make_request(session, bad, GetUpdates()) == []
    finally:
        restore()
