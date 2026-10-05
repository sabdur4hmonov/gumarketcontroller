"""The escalating Yo'q button, run for real (CP17 Part 2).

tests/js/no_button.mjs runs the shipped static/js/page.js under Node against a
minimal DOM and presses Yo'q until it is gone. The rule asserted here: every
press shows a NEW line, in the order written, never one already shown in the
visit; and when the lines run out, the button leaves.

Node is a development tool here, not a runtime dependency; without it the test
is skipped, never silently passed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from gulbot.models.share_page import MUSIC_TRACKS, PAGE_LANGUAGES
from gulbot.web import strings
from gulbot.web.render import STATIC

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tests" / "js" / "no_button.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")


def press_until_gone(lines: tuple[str, ...]) -> dict[str, object]:
    assert NODE is not None
    out = subprocess.run(
        [NODE, str(HARNESS), str(STATIC / "js" / "page.js"), json.dumps(list(lines))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return dict(json.loads(out.strip().splitlines()[-1]))


@pytest.mark.parametrize("lang", PAGE_LANGUAGES)
def test_every_press_says_something_new_and_then_the_button_leaves(lang: str) -> None:
    lines = strings.NO_LINES[lang]
    result = press_until_gone(lines)
    seen = result["seen"]
    assert seen == list(lines[1:]), "the lines must come once each, in order"
    assert len(set(seen)) == len(seen), "a line was repeated within one visit"
    assert result["goneAfter"] == len(lines), "Yo'q must leave exactly when the lines run out"


def run(harness: str, *args: str) -> dict[str, object]:
    assert NODE is not None
    out = subprocess.run(
        [NODE, str(REPO_ROOT / "tests" / "js" / harness), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return dict(json.loads(out.strip().splitlines()[-1]))


@pytest.mark.parametrize("track", MUSIC_TRACKS)
def test_music_never_plays_until_the_visitor_taps(track: str) -> None:
    result = run("music.mjs", str(STATIC / "js" / "music.js"), track)
    before, tap, second = result["before"], result["afterTap"], result["afterSecond"]
    assert isinstance(before, dict) and isinstance(tap, dict) and isinstance(second, dict)
    # Not even an audio context before the tap: nothing can sound.
    assert before["contexts"] == 0 and before["notes"] == 0 and before["shown"] is True
    assert tap["contexts"] == 1 and tap["notes"] > 0 and tap["pressed"] == "true"
    assert second["suspended"] == 1 and second["pressed"] == "false"


def test_a_track_we_do_not_ship_is_never_played() -> None:
    result = run("music.mjs", str(STATIC / "js" / "music.js"), "someones-song")
    before, tap = result["before"], result["afterTap"]
    assert isinstance(before, dict) and isinstance(tap, dict)
    assert before["shown"] is False and tap["contexts"] == 0


def test_the_konvert_letter_opens_section_by_section() -> None:
    result = run("envelope.mjs", str(STATIC / "js" / "page.js"))
    sealed, order = result["sealed"], result["order"]
    assert isinstance(sealed, dict) and isinstance(order, list)
    assert sealed == {"waiting": True, "shown": 0}, "sealed: every section waits"
    assert result["opened"] is True and result["allShown"] is True
    assert [name for name, _ms in order] == ["ornament", "eyebrow", "names", "when", "venue"]
    delays = [ms for _name, ms in order]
    assert delays == sorted(delays) and len(set(delays)) == len(delays), "one after another"
