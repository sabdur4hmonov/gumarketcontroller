"""Free-text labels are cleaned at ENTRY.

These strings are rendered into reminder messages months later, so a bad one
must never reach the database in the first place.
"""

from __future__ import annotations

import pytest

from gulbot.models.occasion import LABEL_MAX_LENGTH
from gulbot.utils.render import escape
from gulbot.utils.text import sanitize_label


def test_cap_is_64() -> None:
    assert LABEL_MAX_LENGTH == 64


def test_long_input_is_capped() -> None:
    assert len(sanitize_label("a" * 500)) == LABEL_MAX_LENGTH


def test_input_at_the_cap_survives_intact() -> None:
    exact = "b" * LABEL_MAX_LENGTH
    assert sanitize_label(exact) == exact


@pytest.mark.parametrize(
    "raw",
    [
        "Singlim\nOnam",
        "Singlim\r\nOnam",
        "Singlim\tOnam",
        "Singlim\x0bOnam",
        "Singlim\x0cOnam",
    ],
)
def test_newlines_and_tabs_collapse_to_a_single_space(raw: str) -> None:
    assert sanitize_label(raw) == "Singlim Onam"


@pytest.mark.parametrize("control", ["\x00", "\x07", "\x1b", "\x7f", "​", "‎", "﻿"])
def test_control_and_invisible_characters_are_stripped(control: str) -> None:
    """Zero-width and bidi marks survive copy-paste and wreck rendering."""
    assert sanitize_label(f"On{control}am") == "Onam"


def test_leading_and_trailing_whitespace_is_removed() -> None:
    assert sanitize_label("   Onam   ") == "Onam"


def test_runs_of_whitespace_collapse() -> None:
    assert sanitize_label("Onam      va      Otam") == "Onam va Otam"


@pytest.mark.parametrize("raw", ["", "   ", "\n\n", "\x00\x00", "​"])
def test_input_with_nothing_left_returns_empty(raw: str) -> None:
    """The handler refuses these rather than storing a blank label."""
    assert sanitize_label(raw) == ""


def test_truncation_does_not_leave_trailing_space() -> None:
    raw = ("word " * 40).strip()
    assert sanitize_label(raw) == sanitize_label(raw).strip()


def test_uzbek_and_russian_text_survives() -> None:
    assert sanitize_label("Turmush o'rtog'im") == "Turmush o'rtog'im"
    assert sanitize_label("Моя сестра") == "Моя сестра"


def test_emoji_survive() -> None:
    assert sanitize_label("Onam 🌹") == "Onam 🌹"


def test_html_is_escaped_at_render_not_at_storage() -> None:
    """The bot runs with parse_mode=HTML.

    Storage keeps the text the customer typed; escaping happens once, on the way
    out, so a label can never be interpreted as markup or break the send.
    """
    label = sanitize_label("<b>Onam</b>")
    assert label == "<b>Onam</b>"
    assert escape(label) == "&lt;b&gt;Onam&lt;/b&gt;"


def test_unbalanced_angle_bracket_is_escaped() -> None:
    """An unclosed tag would otherwise make Telegram reject the whole message."""
    assert escape(sanitize_label("Onam <3")) == "Onam &lt;3"
