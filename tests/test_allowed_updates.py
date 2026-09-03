"""allowed_updates must be declared explicitly.

aiogram otherwise derives the list from the handlers registered at startup. The
CP8 channel indexer would then receive nothing if its router were registered
late or conditionally -- the catalog would simply stay empty, with no error.
"""

from __future__ import annotations

import pytest

from gulbot.bot.factory import ALLOWED_UPDATES


@pytest.mark.parametrize("update_type", ["channel_post", "edited_channel_post"])
def test_channel_updates_are_requested(update_type: str) -> None:
    assert update_type in ALLOWED_UPDATES


def test_core_updates_are_requested() -> None:
    assert {"message", "callback_query"} <= set(ALLOWED_UPDATES)


def test_no_duplicates() -> None:
    assert len(ALLOWED_UPDATES) == len(set(ALLOWED_UPDATES))
