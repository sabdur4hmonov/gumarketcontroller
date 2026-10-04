"""The test suite's alert cooldowns never share keys with another run or with
the real namespace (see `alert_cooldowns_of_this_session_only` in conftest)."""

from __future__ import annotations

from gulbot.sending import health


def test_this_session_claims_under_its_own_prefix(
    alert_cooldowns_of_this_session_only: str,
) -> None:
    assert alert_cooldowns_of_this_session_only == health.ALERT_KEY
    assert health.ALERT_KEY.startswith("gulbot:test-alert:")
    assert health.ALERT_KEY != "gulbot:alert"
