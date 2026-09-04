"""The catalogue's pure layer stays pure, and CP7 stays out of CP8.

Same shape as CP4's purity guard and CP5/CP6's scope fences. Two separate
claims:

  * `gulbot.catalog.hashtags` and `gulbot.catalog.prices` are pure functions --
    no database, no Telegram, no settings, not even transitively;
  * nothing in CP7 talks to the Bot API. Indexing channel posts is CP8.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

PURE_MODULES = ("gulbot.catalog.hashtags", "gulbot.catalog.prices")

CATALOG_FILES = (
    REPO_ROOT / "src/gulbot/catalog/hashtags.py",
    REPO_ROOT / "src/gulbot/catalog/prices.py",
    REPO_ROOT / "src/gulbot/catalog/alias_fixture.py",
)

#: Case-sensitive. Nothing in CP7 may reach for a Telegram client or a session.
FORBIDDEN_TOKENS = (
    "aiogram",
    "telegram",
    "Bot(",
    "send_message",
    "copyMessage",
    "AsyncSession",
    "sqlalchemy",
    "get_settings",
)


def code_only(path: Path) -> str:
    """Source with comments and string literals stripped.

    These modules explain in prose that they touch no database, which a naive
    substring scan would read as evidence that they do.
    """
    kept: list[str] = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(io.BytesIO(handle.read()).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


@pytest.mark.parametrize("path", CATALOG_FILES, ids=lambda p: p.name)
def test_the_pure_layer_names_no_io(path: Path) -> None:
    source = code_only(path)
    for token in FORBIDDEN_TOKENS:
        assert token not in source, f"{path.name} reaches for {token}"


@pytest.mark.parametrize("module", PURE_MODULES)
def test_importing_the_pure_layer_pulls_in_no_io(module: str) -> None:
    """Checked in a FRESH interpreter, so transitive imports count.

    Importing in-process would pass trivially: pytest has already imported
    sqlalchemy and aiogram by the time any test runs.
    """
    program = (
        "import sys\n"
        f"import {module}\n"
        "watched = ('sqlalchemy', 'aiogram', 'psycopg', 'celery', 'redis',\n"
        "           'gulbot.db', 'gulbot.models', 'gulbot.config')\n"
        "leaked = sorted(m for m in sys.modules if m.startswith(watched))\n"
        "print(','.join(leaked))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    assert result.stdout.strip() == "", f"{module} pulled in: {result.stdout.strip()}"


def test_the_pure_functions_need_no_arguments_beyond_their_input() -> None:
    """A function that reads config is not pure, whatever its imports say."""
    import inspect

    from gulbot.catalog.hashtags import normalize_hashtag
    from gulbot.catalog.prices import parse_price

    assert list(inspect.signature(normalize_hashtag).parameters) == ["raw"]
    assert list(inspect.signature(parse_price).parameters) == ["caption"]


def test_no_telegram_anywhere_in_cp7() -> None:
    """The scope fence proper: CP8 owns the indexer, not this checkpoint."""
    offenders = []
    for path in (REPO_ROOT / "src/gulbot/catalog").rglob("*.py"):
        source = code_only(path).lower()
        if "aiogram" in source or "telegram" in source:
            offenders.append(path.name)
    assert not offenders, f"CP7 grew a Telegram dependency: {offenders}"


def test_the_seed_service_is_allowed_a_session_but_not_a_bot() -> None:
    """The seeder is NOT in the pure layer; it may use a session, not a Bot."""
    source = code_only(REPO_ROOT / "src/gulbot/services/hashtag_aliases.py")
    assert "AsyncSession" in source, "the seeder should be taking a session"
    for token in ("aiogram", "Bot(", "send_message"):
        assert token not in source, f"the seeder reaches for {token}"
