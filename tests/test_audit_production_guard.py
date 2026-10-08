"""The production-config guard: the single most important fix in the audit.

A deploy that forgets one environment variable must not quietly run the pilot
on the dev bot token or the dev database. pydantic-settings falls back to `.env`
in the working directory, then to defaults that ARE the dev setup; pass 6
reproduced both before the guard existed. See `gulbot.config` for the rule.

TWO LAYERS OF TESTS, on purpose.

  * Unit tests of the rule, one case per required variable, so dropping any
    single check fails a test named after it. The variable names are written out
    here rather than read from PRODUCTION_REQUIRED_ENV -- a test that iterated
    the tuple would shrink along with it and pass.
  * REAL PROCESSES: every entrypoint is started as the deploy would start it,
    with ENVIRONMENT=production and dev-shaped config, and must exit non-zero
    with the refusal. And a production-shaped config must get past the guard.
    A guard that only worked when called from a test would be worth nothing.

No real secret is used. Children get fake markers through the environment and a
fake dev-shaped `.env` in their working directory -- except the alembic case,
which must run from the repo; that one asserts the real dev token is NOT in the
output.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gulbot.config import (
    DEV_DEFAULT_PASSWORD,
    PRODUCTION_REQUIRED_ENV,
    ProductionConfigError,
    Settings,
    check_production_config,
    get_settings,
    production_config_problems,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CELERY = str(Path(sys.executable).with_name("celery.exe" if os.name == "nt" else "celery"))

DEV_TOKEN = "987654321:DEVmarkerDEVmarkerDEVmarkerDEVmarker"
PROD_TOKEN = "123456789:PRODmarkerPRODmarkerPRODmarkerPRODmark"
PROD_PASSWORD = "prod-pw-marker-41c9e7"

#: What a correct production deploy exports.
PRODUCTION_ENV = {
    "ENVIRONMENT": "production",
    "BOT_TOKEN": PROD_TOKEN,
    "POSTGRES_HOST": "db.prod.internal",
    "POSTGRES_DB": "gulbot_prod",
    "POSTGRES_PASSWORD": PROD_PASSWORD,
    # CP18: production refuses to start with nobody able to log into the panel.
    "PLATFORM_ADMIN_TELEGRAM_IDS": "424242",
}

#: Written out, not taken from PRODUCTION_REQUIRED_ENV. See the module docstring.
REQUIRED = ["BOT_TOKEN", "POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_PASSWORD"]

#: A stale dev `.env`, the file a careless deploy leaves in the working directory.
DEV_ENV_FILE = (
    f"BOT_TOKEN={DEV_TOKEN}\n"
    "POSTGRES_HOST=localhost\n"
    "POSTGRES_DB=gulbot\n"
    f"POSTGRES_PASSWORD={DEV_DEFAULT_PASSWORD}\n"
    "ENVIRONMENT=local\n"
)


def production_settings(**overrides: str) -> Settings:
    values = {
        "environment": "production",
        "bot_token": PROD_TOKEN,
        "postgres_host": "db.prod.internal",
        "postgres_db": "gulbot_prod",
        "postgres_password": PROD_PASSWORD,
        "platform_admin_telegram_ids": "424242",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------


def test_the_required_list_is_exactly_the_four_that_decide_where_traffic_goes() -> None:
    assert list(PRODUCTION_REQUIRED_ENV) == REQUIRED


def test_production_shaped_config_passes() -> None:
    """CONFIRMATION. The guard must not stop a correct deploy."""
    assert production_config_problems(production_settings(), PRODUCTION_ENV) == []
    check_production_config(production_settings(), PRODUCTION_ENV)


@pytest.mark.parametrize("missing", REQUIRED)
def test_each_required_variable_missing_from_the_real_environment_is_refused(
    missing: str,
) -> None:
    """DEFECT IF THIS FAILS. The value is still present in Settings -- as if it
    had come from `.env` or a default -- but not in the real environment."""
    environ = {k: v for k, v in PRODUCTION_ENV.items() if k != missing}
    problems = production_config_problems(production_settings(), environ)
    assert any(p.startswith(f"{missing} ") for p in problems), problems
    with pytest.raises(ProductionConfigError, match=missing):
        check_production_config(production_settings(), environ)


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize("name", REQUIRED)
def test_a_required_variable_set_but_empty_is_refused(name: str, blank: str) -> None:
    """`BOT_TOKEN=` exported with nothing after it is not a choice either."""
    environ = {**PRODUCTION_ENV, name: blank}
    with pytest.raises(ProductionConfigError, match=name):
        check_production_config(production_settings(), environ)


def test_the_dev_password_is_refused_even_when_really_exported() -> None:
    """DEFECT IF THIS FAILS. Check (b): every variable is a real one, and the
    password is still the dev default."""
    environ = {**PRODUCTION_ENV, "POSTGRES_PASSWORD": DEV_DEFAULT_PASSWORD}
    settings = production_settings(postgres_password=DEV_DEFAULT_PASSWORD)
    with pytest.raises(ProductionConfigError, match="dev default password"):
        check_production_config(settings, environ)


@pytest.mark.parametrize("spelling", ["production", "Production", " PRODUCTION ", "production\n"])
def test_the_guard_is_armed_however_production_is_spelled(spelling: str) -> None:
    with pytest.raises(ProductionConfigError):
        check_production_config(production_settings(environment=spelling), {})


@pytest.mark.parametrize("environment", ["local", "test", ""])
def test_dev_config_outside_production_is_left_alone(environment: str) -> None:
    """CONFIRMATION. The guard is for production only; local development and the
    suite run on exactly the defaults it refuses."""
    assert production_config_problems(Settings(environment=environment), {}) == []


def test_every_problem_is_reported_at_once_and_no_value_is_printed() -> None:
    """One restart per missing variable is how a deploy at midnight goes wrong.
    And the refusal must not print what it refuses."""
    settings = production_settings(bot_token=DEV_TOKEN, postgres_password=DEV_DEFAULT_PASSWORD)
    with pytest.raises(ProductionConfigError) as caught:
        check_production_config(settings, {"ENVIRONMENT": "production"})
    message = str(caught.value)
    assert message.startswith("REFUSING TO START")
    for name in REQUIRED:
        assert name in message
    assert "dev default password" in message
    assert DEV_TOKEN.split(":")[1] not in message
    assert PROD_PASSWORD not in message


def test_get_settings_itself_enforces_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEFECT IF THIS FAILS. The chokepoint every process goes through, with the
    real environment and a real dev `.env` in the working directory."""
    (tmp_path / ".env").write_text(DEV_ENV_FILE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for name in (*REQUIRED, "ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    try:
        with pytest.raises(ProductionConfigError):
            get_settings()
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# real processes
# ---------------------------------------------------------------------------


def _child_env(**values: str) -> dict[str, str]:
    """The parent's environment without anything the guard looks at."""
    stripped = {
        k: v
        for k, v in os.environ.items()
        if k.upper() not in {*REQUIRED, "ENVIRONMENT"} and not k.upper().startswith("POSTGRES_")
    }
    return {**stripped, **values}


def _run(cmd: list[str], *, env: dict[str, str], cwd: Path, timeout: float = 90) -> tuple[int, str]:
    started = time.monotonic()
    try:
        run = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
        pytest.fail(
            f"{cmd[1:4]} was still running after {timeout}s -- it STARTED instead of "
            f"refusing:\n{out[-1500:]}"
        )
    print(
        f"\n  {' '.join(Path(c).name for c in cmd[:5])}: exit {run.returncode} "
        f"in {time.monotonic() - started:.1f}s"
    )
    return run.returncode, run.stdout + run.stderr


@pytest.fixture
def stale_dev_dir(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text(DEV_ENV_FILE, encoding="utf-8")
    return tmp_path


def _assert_refused(code: int, output: str) -> None:
    assert code != 0, f"the process exited 0:\n{output[-1500:]}"
    assert "ProductionConfigError" in output, output[-1500:]
    assert "REFUSING TO START" in output, output[-1500:]
    assert DEV_TOKEN.split(":")[1] not in output, "the refusal printed the token"


def test_the_bot_refuses_to_start_on_dev_config(stale_dev_dir: Path) -> None:
    """DEFECT IF THIS FAILS. `python -m gulbot.bot.run`, as deployed, with
    ENVIRONMENT=production and everything else coming from a stale dev `.env`."""
    code, output = _run(
        [sys.executable, "-m", "gulbot.bot.run"],
        env=_child_env(ENVIRONMENT="production"),
        cwd=stale_dev_dir,
    )
    _assert_refused(code, output)
    for name in REQUIRED:
        assert name in output


@pytest.mark.parametrize("missing", REQUIRED)
def test_the_bot_refuses_when_one_variable_is_forgotten(stale_dev_dir: Path, missing: str) -> None:
    """DEFECT IF THIS FAILS. The exact deploy the guard exists for: three of four
    exported, the fourth silently supplied by the stale `.env`."""
    values = {k: v for k, v in PRODUCTION_ENV.items() if k != missing}
    code, output = _run(
        [sys.executable, "-m", "gulbot.bot.run"], env=_child_env(**values), cwd=stale_dev_dir
    )
    _assert_refused(code, output)
    assert missing in output


@pytest.mark.parametrize(
    "command",
    [
        ["worker", "--pool=solo", "--loglevel=info"],
        ["beat", "--loglevel=info"],
    ],
    ids=["worker", "beat"],
)
def test_the_celery_processes_refuse_to_start_on_dev_config(
    stale_dev_dir: Path, command: list[str]
) -> None:
    code, output = _run(
        [CELERY, "-A", "gulbot.worker.app", *command],
        env=_child_env(ENVIRONMENT="production"),
        cwd=stale_dev_dir,
    )
    _assert_refused(code, output)


def test_the_seed_cli_refuses_to_start_on_dev_config(stale_dev_dir: Path) -> None:
    code, output = _run(
        [sys.executable, "-m", "gulbot.cli.seed"],
        env=_child_env(ENVIRONMENT="production"),
        cwd=stale_dev_dir,
    )
    _assert_refused(code, output)


def test_migrations_refuse_to_run_on_dev_config() -> None:
    """Migrating the wrong database is the same failure. Alembic resolves its
    script location from the repo, so this child runs THERE -- against the real
    dev `.env` -- and must not print the dev token while refusing."""
    code, output = _run(
        [sys.executable, "-m", "alembic", "current"],
        env=_child_env(ENVIRONMENT="production"),
        cwd=REPO_ROOT,
    )
    _assert_refused(code, output)
    real_token = get_settings().bot_token.get_secret_value()
    if real_token:
        assert real_token.split(":")[-1] not in output


def test_production_shaped_config_starts_cleanly(stale_dev_dir: Path) -> None:
    """CONFIRMATION. A correct deploy gets its settings -- from the real
    environment, not from the stale `.env` sitting next to it."""
    probe = (
        "import os\n"
        "from gulbot.config import get_settings\n"
        "s = get_settings()\n"
        "print('CONFIG OK', s.environment, s.postgres_host, s.postgres_db)\n"
        "print('token from env:', s.bot_token.get_secret_value() == os.environ['BOT_TOKEN'])\n"
    )
    code, output = _run(
        [sys.executable, "-c", probe], env=_child_env(**PRODUCTION_ENV), cwd=stale_dev_dir
    )
    assert code == 0, output[-1500:]
    assert "CONFIG OK production db.prod.internal gulbot_prod" in output
    assert "token from env: True" in output


def test_the_celery_app_loads_cleanly_on_production_config(stale_dev_dir: Path) -> None:
    """`celery report` imports the app -- where the guard runs -- without
    connecting to a broker."""
    code, output = _run(
        [CELERY, "-A", "gulbot.worker.app", "report"],
        env=_child_env(**PRODUCTION_ENV),
        cwd=stale_dev_dir,
    )
    assert code == 0, output[-1500:]
    assert "ProductionConfigError" not in output


def test_the_bot_gets_past_the_guard_on_production_config(stale_dev_dir: Path) -> None:
    """CONFIRMATION. With production-shaped config the bot process passes the
    guard and goes on to its next startup step, connecting to the database --
    pointed here at a closed local port, so that step fails, and fails with a
    connection error rather than the refusal."""
    env = _child_env(**{**PRODUCTION_ENV, "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "1"})
    code, output = _run([sys.executable, "-m", "gulbot.bot.run"], env=env, cwd=stale_dev_dir)
    assert "ProductionConfigError" not in output
    assert "REFUSING TO START" not in output
    assert code != 0
    assert any(
        marker in output
        for marker in ("ConnectionRefusedError", "Connect call failed", "OSError", "TimeoutError")
    ), output[-1500:]
