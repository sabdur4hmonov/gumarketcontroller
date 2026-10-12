"""The vendored dictionary and fonts are stored IN GIT as their upstream bytes.

Found by CP23's gate, in a fresh worktree: CP22 committed the hunspell files
while they were still treated as text, so git stored them with LF while the
upstream files -- and the hashes pinned in SOURCE.json -- have CRLF. On the
Windows machine that committed them the working copies were still the
upstream bytes and every test passed; every FRESH checkout (a gate worktree,
a production server) got different bytes. This test asks git itself, so a
working copy can never hide it again.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "gulbot" / "announcements" / "assets"


@pytest.mark.parametrize("directory", ["dictionary", "fonts"])
def test_git_stores_the_pinned_upstream_bytes(directory: str) -> None:
    manifest = json.loads((ASSETS / directory / "SOURCE.json").read_text(encoding="utf-8"))
    assert manifest["files"], "an empty manifest pins nothing"
    for item in manifest["files"]:
        path = (ASSETS / directory / item["name"]).relative_to(ROOT).as_posix()
        stored = subprocess.run(
            ["git", "cat-file", "blob", f":{path}"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        assert len(stored) == item["bytes"], path
        assert hashlib.sha256(stored).hexdigest() == item["sha256"], path
