"""Makefile and make.ps1 must expose the same targets.

`make` is not installed on the Windows dev box, so make.ps1 is what actually
runs here -- but the Makefile is canonical. If they drift, someone runs `check`
and gets a different gate than CI does, and the gate stops meaning anything.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

GATE_STEPS = ("lint", "typecheck", "shadow", "test")


def makefile_targets() -> set[str]:
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^\.PHONY:(.*)$", text, re.MULTILINE)
    assert match, "Makefile has no .PHONY line"
    return set(match.group(1).split())


def powershell_targets() -> set[str]:
    """Targets in the $Steps table, plus those the switch handles itself."""
    text = (REPO_ROOT / "make.ps1").read_text(encoding="utf-8")
    steps_block = text.split("$Steps = @{", 1)[1].split("\n}", 1)[0]
    targets = set(re.findall(r'^\s*"([a-z]+)"\s*=', steps_block, re.MULTILINE))
    switch_block = text.split("switch ($Target)", 1)[1]
    targets |= set(re.findall(r'^\s*"([a-z]+)"\s*\{', switch_block, re.MULTILINE))
    return targets


def test_target_lists_match() -> None:
    make, ps = makefile_targets(), powershell_targets()
    assert make == ps, (
        f"only in Makefile: {sorted(make - ps)}; only in make.ps1: {sorted(ps - make)}"
    )


def test_check_is_the_gate_in_both() -> None:
    assert "check" in makefile_targets()
    assert "check" in powershell_targets()


def test_both_gates_run_the_same_steps_in_the_same_order() -> None:
    """A gate that means different things in two places is not a gate."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^check:(.*)$", makefile, re.MULTILINE)
    assert match, "Makefile has no check target"
    assert tuple(match.group(1).split()) == GATE_STEPS

    shim = (REPO_ROOT / "make.ps1").read_text(encoding="utf-8")
    match = re.search(r"\$CheckSteps\s*=\s*@\((.*?)\)", shim, re.DOTALL)
    assert match, "make.ps1 has no $CheckSteps"
    assert tuple(re.findall(r'"([a-z]+)"', match.group(1))) == GATE_STEPS


def test_shadow_sweep_is_in_the_gate() -> None:
    """It is a build gate, not an optional check."""
    assert "shadow" in GATE_STEPS
    assert "shadow" in makefile_targets()
    assert "shadow" in powershell_targets()
