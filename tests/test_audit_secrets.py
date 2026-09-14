"""PASS 6: configuration and secrets.

Two defects found, both reproduced live before these tests existed:

1. THE BOT TOKEN IN TEST OUTPUT. pydantic's repr of `Settings` printed every
   field in the clear. pytest prints that repr in any failing assertion whose
   expression touches a Settings object, and in `-l` tracebacks. The live run
   put the real dev token into pytest's output.

2. ENV FILES OTHER THAN `.env` WERE NOT IGNORED. `.gitignore` named `.env`
   exactly, so `.env.production`, `.env.local` and the like were one `git add .`
   away from being committed.

No marker here is a real secret. The subprocess test hands the child process
fake values through the environment, which pydantic-settings prefers over
`.env`, so the real dev token is never loaded by these tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import gulbot.bot.factory as factory_module
from gulbot.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]

MARKER_TOKEN = "123456789:MARKERmarkerMARKERmarkerMARKERmarkerXX"
MARKER_SECRET = MARKER_TOKEN.split(":", 1)[1]
MARKER_PASSWORD = "pw-marker-6b1f0e93"


def test_no_rendering_of_settings_shows_a_secret() -> None:
    """DEFECT IF THIS FAILS. Every ordinary way an object ends up in a log line
    or an error message."""
    settings = Settings(bot_token=MARKER_TOKEN, postgres_password=MARKER_PASSWORD)
    renderings = {
        "repr": repr(settings),
        "str": str(settings),
        "f-string": f"{settings}",
        "%s": "%s" % settings,  # noqa: UP031
        "model_dump": repr(settings.model_dump()),
        "field str": f"{settings.bot_token} {settings.postgres_password}",
    }
    for how, text in renderings.items():
        assert MARKER_SECRET not in text, f"the bot token shows in {how}"
        assert MARKER_PASSWORD not in text, f"the database password shows in {how}"


def test_the_secrets_still_reach_the_two_places_that_need_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GUARDS THE GUARD. A masked value that reached the connection string or the
    Bot would fail authentication -- loudly, but in production."""
    settings = Settings(bot_token=MARKER_TOKEN, postgres_password=MARKER_PASSWORD)
    assert f":{MARKER_PASSWORD}@" in settings.database_url()

    monkeypatch.setattr(factory_module, "get_settings", lambda: settings)
    assert factory_module.build_bot().token == MARKER_TOKEN


def test_a_failing_pytest_assertion_does_not_print_the_token(tmp_path: Path) -> None:
    """DEFECT IF THIS FAILS. The live leak path, run for real: a child pytest with
    a failing assertion about Settings, tracebacks with locals (`-l`)."""
    probe = tmp_path / "test_leak_probe.py"
    probe.write_text(
        textwrap.dedent(
            """
            from gulbot.config import get_settings

            def test_about_a_field():
                settings = get_settings()
                assert settings.log_level == "A VALUE IT IS NOT"

            def test_about_the_object():
                assert get_settings() == object()
            """
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "BOT_TOKEN": MARKER_TOKEN, "POSTGRES_PASSWORD": MARKER_PASSWORD}
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(probe),
            "-l",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "--rootdir",
            str(tmp_path),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = run.stdout + run.stderr

    assert run.returncode == 1, f"the probe should fail twice:\n{output[-2000:]}"
    assert "Settings(" in output, "the repr was never printed; the leak path was not exercised"
    assert MARKER_SECRET not in output, "pytest printed the bot token"
    assert MARKER_PASSWORD not in output, "pytest printed the database password"


def _ignored(name: str) -> bool:
    run = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", name], cwd=REPO_ROOT, capture_output=True
    )
    return run.returncode == 0


@pytest.mark.parametrize(
    "name", [".env", ".env.local", ".env.production", ".env.prod", ".env.backup"]
)
def test_every_env_file_is_ignored(name: str) -> None:
    """DEFECT IF THIS FAILS. `--no-index` asks the ignore rules themselves, so a
    file that happens to exist or not on this machine changes nothing."""
    assert _ignored(name), f"{name} is not gitignored"


def test_the_example_env_file_is_not_ignored() -> None:
    """GUARDS THE GUARD. The template has to stay committable."""
    assert not _ignored(".env.example")


def test_no_env_file_but_the_example_was_ever_committed() -> None:
    """Across every commit, not just the working tree."""
    run = subprocess.run(
        ["git", "log", "--all", "--name-only", "--format="],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    committed = {line for line in run.stdout.splitlines() if line.strip()}
    env_files = {
        path
        for path in committed
        if Path(path).name.startswith(".env") and Path(path).name != ".env.example"
    }
    assert env_files == set()
