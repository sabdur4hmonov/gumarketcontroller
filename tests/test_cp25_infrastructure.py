"""Units and missing telemetry must not produce a plausible capacity table."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest
from scripts.cp25_load import infrastructure


@pytest.mark.parametrize(
    "size, expected", [("1GiB", 1024), ("512MiB", 512), ("1048576B", 1), ("1MB", 1000000 / 1048576)]
)
def test_container_memory_units(size: str, expected: float) -> None:
    assert infrastructure.memory_mib(size) == expected


def test_missing_container_is_not_zero_usage(monkeypatch) -> None:
    run = Mock(spec=subprocess.CompletedProcess)
    run.stdout = '{"Name":"gulbot-postgres","CPUPerc":"1%","MemUsage":"25MiB / 8GiB"}'
    monkeypatch.setattr(infrastructure.subprocess, "run", lambda *a, **k: run)
    with pytest.raises(ValueError, match="Both"):
        infrastructure.docker_sample()


def test_resource_window_requires_more_than_one_sample() -> None:
    meter = infrastructure.Infrastructure()
    with pytest.raises(ValueError, match="incomplete"):
        meter.result()
