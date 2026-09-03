"""Makefile and make.ps1 must expose the same targets.

`make` is not installed on the Windows dev box, so make.ps1 is what actually
runs here -- but the Makefile is canonical. If they drift, someone runs `check`
and gets a different gate than CI does, and the gate stops meaning anything.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def makefile_targets() -> set[str]:
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^\.PHONY:(.*)$", text, re.MULTILINE)
    assert match, "Makefile has no .PHONY line"
    return set(match.group(1).split())


def powershell_targets() -> set[str]:
    text = (REPO_ROOT / "make.ps1").read_text(encoding="utf-8")
    body = text.split("switch ($Target)", 1)[1]
    return set(re.findall(r'^\s*"([a-z]+)"\s*\{', body, re.MULTILINE))


def test_target_lists_match() -> None:
    make, ps = makefile_targets(), powershell_targets()
    assert make == ps, (
        f"only in Makefile: {sorted(make - ps)}; only in make.ps1: {sorted(ps - make)}"
    )


def test_check_is_the_gate_in_both() -> None:
    assert "check" in makefile_targets()
    assert "check" in powershell_targets()
