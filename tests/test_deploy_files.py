"""CP21 guards on the files deploy/ installs on the server.

The staging rehearsal proved these files on a stand-in server; these tests keep
a later edit -- made on Windows, where nothing here ever runs -- from quietly
undoing what it proved:

  * every shell script is executable IN GIT: a Windows checkout cannot show
    the mode, and a fresh Linux clone of a 0644 script makes the backup
    unit fail at 03:10 with "Permission denied", every night, silently;
  * every unit's ExecStart names a file the repo really has, at the path the
    clone puts it;
  * the worker is prefork (the task time limits exist only there);
  * the rehearsal's Postgres and Redis publish nothing, and its one published
    port is on this machine's loopback;
  * the runbook says, in so many words, that the encryption key is backed up
    OUTSIDE the server.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = REPO_ROOT / "deploy"
#: Where DEPLOY step 3 clones the repo.
SERVER_ROOT = "/opt/gulbot/"

UNIT_FILES = sorted(
    [*DEPLOY.glob("systemd/*.service"), *DEPLOY.glob("backup/*.service")],
    key=lambda path: path.name,
)


def _git_modes(path: str) -> dict[str, str]:
    listed = subprocess.run(
        ["git", "ls-files", "-s", "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    modes = {}
    for line in listed.splitlines():
        meta, name = line.split("\t", 1)
        modes[name] = meta.split()[0]
    return modes


def _exec_start(unit: Path) -> str:
    found = re.search(r"^ExecStart=(\S+)", unit.read_text(encoding="utf-8"), re.MULTILINE)
    assert found, f"{unit.name} has no ExecStart"
    return found.group(1)


def test_every_deploy_shell_script_is_executable_in_git() -> None:
    modes = _git_modes("deploy")
    scripts = {name: mode for name, mode in modes.items() if name.endswith(".sh")}
    assert scripts, "no shell scripts tracked under deploy/ -- is this test looking at the repo?"
    assert {name: mode for name, mode in scripts.items() if mode != "100755"} == {}


def test_the_units_are_the_ones_tracked() -> None:
    """Vacuity guard: the parametrized checks below must see every unit."""
    tracked = {name for name in _git_modes("deploy") if name.endswith(".service")}
    assert {str(unit.relative_to(REPO_ROOT)).replace("\\", "/") for unit in UNIT_FILES} == tracked
    assert len(UNIT_FILES) == 5


@pytest.mark.parametrize("unit", UNIT_FILES, ids=lambda unit: unit.name)
def test_every_exec_start_names_a_file_the_clone_has(unit: Path) -> None:
    command = _exec_start(unit)
    assert command.startswith(SERVER_ROOT), command
    relative = command.removeprefix(SERVER_ROOT)
    if relative.startswith(".venv/"):
        # Made by step 3's `pip install`, not tracked; the module it runs is.
        return
    assert (REPO_ROOT / relative).is_file(), f"{unit.name} runs {command}, which the repo lacks"


def test_the_worker_is_prefork() -> None:
    command = (DEPLOY / "systemd" / "gulbot-worker.service").read_text(encoding="utf-8")
    exec_line = next(line for line in command.splitlines() if line.startswith("ExecStart="))
    assert "--pool=prefork" in exec_line
    assert "solo" not in exec_line


def test_the_backup_timer_catches_up_after_downtime() -> None:
    timer = (DEPLOY / "backup" / "gulbot-backup.timer").read_text(encoding="utf-8")
    assert re.search(r"^OnCalendar=\*-\*-\* 03:10:00 Asia/Tashkent$", timer, re.MULTILINE)
    assert re.search(r"^Persistent=true$", timer, re.MULTILINE)


def test_the_rehearsal_publishes_only_loopback_and_never_the_data_stores() -> None:
    compose = yaml.safe_load((DEPLOY / "rehearsal" / "compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    for store in ("postgres", "redis"):
        assert services[store]["network_mode"] == "service:server", store
        assert "ports" not in services[store], store
    assert all(port.startswith("127.0.0.1:") for port in services["server"]["ports"])


def test_the_runbook_says_the_key_is_backed_up_outside_the_server() -> None:
    runbook = " ".join((REPO_ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8").split())
    assert "`SHOP_TOKEN_ENCRYPTION_KEY` is backed up OUTSIDE the server" in runbook
