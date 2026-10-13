"""Small scale admission is checked without resetting any real database."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from scripts.cp25_load import capacity, load_seed


@pytest.mark.parametrize("shops", [10, 25, 50])
def test_small_scale_reaches_the_owned_seed_boundary(monkeypatch, shops) -> None:
    reset = Mock(side_effect=RuntimeError("owned reset boundary"))
    monkeypatch.setattr(load_seed, "reset_owned_database", reset)
    error = ""
    try:
        load_seed.seed(shops)
    except (RuntimeError, ValueError) as caught:
        error = str(caught)
    assert error == "owned reset boundary", "A bounded small scale must be admitted"
    reset.assert_called_once_with()


@pytest.mark.parametrize("shops", [0, 11, 51, 1001])
def test_unapproved_scale_never_resets_a_database(monkeypatch, shops) -> None:
    reset = Mock(side_effect=RuntimeError("reset called"))
    monkeypatch.setattr(load_seed, "reset_owned_database", reset)
    refused = False
    try:
        load_seed.seed(shops)
    except (ValueError, RuntimeError) as caught:
        refused = isinstance(caught, ValueError)
    assert refused, "The fixture must stay bounded"
    reset.assert_not_called()


async def test_heavy_scale_requires_three_gib_before_seed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(capacity, "available_mib", lambda: 2048)
    seed = Mock(side_effect=RuntimeError("seed boundary"))
    monkeypatch.setattr(load_seed, "seed", seed)
    message = ""
    try:
        await capacity._run_owned_scale(100, tmp_path / "not-created", "none")
    except RuntimeError as caught:
        message = str(caught)
    assert "3072" in message, "Heavy jobs require 3 GiB even if the ordinary startup floor passes"
    seed.assert_not_called()
