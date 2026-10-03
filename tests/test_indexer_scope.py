"""CP8's scope fence: the indexer stays out of CP9 and CP6.

Same shape as CP4's purity guard and CP5/CP6/CP7's fences, and the same reason
for existing: the natural place to write "and while we are here, send the
customer a bouquet" is inside the handler that just indexed one.

Three separate claims:

* the indexer's own source names nothing from the send path or the
  customer-facing routers;
* importing it in a FRESH interpreter pulls neither of those in, so a
  transitive import counts too;
* it builds nothing CP9 owns -- no search, no copyMessage, no reply.

Also fenced: the DELETION SWEEP and the monitoring probe. Both are Phase 2 in
docs/CHECKPOINTS.md, both look like two harmless lines from inside this code,
and `deleted_at` must stay unset by anything in this checkpoint.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

INDEXER_FILES = (
    REPO_ROOT / "src/gulbot/services/indexer.py",
    REPO_ROOT / "src/gulbot/bot/channel.py",
    REPO_ROOT / "src/gulbot/catalog/naming.py",
    REPO_ROOT / "src/gulbot/worker/debounce.py",
)

#: CP9 territory. Case-sensitive where it needs to be.
FORBIDDEN = (
    "copyMessage",
    "copy_message",
    "send_photo",
    "sendPhoto",
    "answer",
    "reply_markup",
    "render_reminder",
    "run_tick",
    "Transport",
    # Phase 2, not "a natural two-line addition while you are in this code".
    "deleted_at",
    "self_probe",
)


def code_only(path: Path) -> str:
    """Source with comments and string literals stripped.

    These modules explain at length what they do NOT do, which a naive
    substring scan would read as evidence that they do it.
    """
    kept: list[str] = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(io.BytesIO(handle.read()).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


@pytest.mark.parametrize("path", INDEXER_FILES, ids=lambda p: p.name)
def test_the_indexer_names_nothing_from_cp9(path: Path) -> None:
    source = code_only(path)
    for token in FORBIDDEN:
        assert token not in source, f"{path.name} reaches into CP9 or Phase 2: {token}"


@pytest.mark.parametrize("path", INDEXER_FILES, ids=lambda p: p.name)
def test_the_indexer_does_not_import_the_customer_facing_layers(path: Path) -> None:
    source = code_only(path)
    for token in ("gulbot.sending", "gulbot.bot.routers", "gulbot.bot.keyboards", "gulbot.i18n"):
        assert token not in source, f"{path.name} imports {token}"


def test_importing_the_indexer_pulls_in_neither_the_send_path_nor_the_routers() -> None:
    """FRESH interpreter, so a transitive import counts.

    In-process this would pass trivially: by the time any test runs, pytest has
    already imported the whole package.
    """
    program = (
        "import sys\n"
        "import gulbot.bot.channel, gulbot.services.indexer\n"
        "watched = ('gulbot.sending', 'gulbot.bot.routers', 'gulbot.bot.keyboards',\n"
        "           'gulbot.i18n')\n"
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
    assert result.stdout.strip() == "", f"the indexer pulled in: {result.stdout.strip()}"


def test_the_scheduler_is_the_seam_and_it_is_injected() -> None:
    """The indexer asks for an album to be settled; it does not know how.

    That is what lets the flow tests drive the real dispatcher without Celery,
    and it is why `gulbot.worker.tasks` -- which imports the send path at module
    level -- is never reachable from a channel handler.
    """
    import inspect

    from gulbot.bot.factory import build_dispatcher

    assert "schedule_finalize" in inspect.signature(build_dispatcher).parameters


#: Modules that write a `deleted_at` of their OWN table -- never the products
#: one. CP16's share_pages has its own column (a deleted page is scrubbed and
#: kept for the shop's counts). Named, so a third writer is a decision.
OTHER_TABLES_DELETED_AT_WRITERS = frozenset({"share_pages.py"})


def test_nothing_in_this_checkpoint_sets_deleted_at() -> None:
    """products.deleted_at: CP9's search should still filter on it
    defensively; nothing writes it.

    The claim is about the PRODUCTS column. It used to be checked as "no
    `deleted_at =` anywhere", which was true only while products had the one
    such column in the schema; CP16 added share_pages.deleted_at and the proxy
    fired on correct code. The module that writes that one is named above and
    must never name Product.
    """
    for path in (REPO_ROOT / "src/gulbot").rglob("*.py"):
        source = code_only(path)
        if "deleted_at =" not in source:
            continue
        assert path.name in OTHER_TABLES_DELETED_AT_WRITERS, f"{path.name} sets deleted_at"
        assert "Product" not in source, f"{path.name} sets deleted_at and names Product"
