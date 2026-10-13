"""Clock injection proves the threshold without a CPU benchmark or stopwatch."""

from __future__ import annotations

import pytest

from gulbot.bot.loop_lag import LagMeter


def test_delayed_loop_is_reported_and_normal_timing_recovers() -> None:
    meter = LagMeter(0)
    assert meter.observe(0.2) == pytest.approx(0.15), "Flag more than ~100ms of loop delay"
    assert meter.observe(0.26) is None, "Do not keep attributing an old stall to new ticks"


def test_normal_scheduler_jitter_does_not_raise_an_alarm() -> None:
    meter = LagMeter(0)
    assert meter.observe(0.07) is None
    assert meter.observe(0.13) is None
