"""CP10's scope fence: an order is PLACED and then left alone.

Confirm, reject, delivered, customer-facing status updates, peak mode and the
escalation ladder are all Phase 2, already named in docs/CHECKPOINTS.md. Every
one of them is a small, plausible-looking addition to the module that just
wrote the order -- which is exactly why the fence exists rather than a comment.

The five statuses are in the CHECK from the start on purpose. The fence is not
"the words must not appear in the schema", it is "no code may MOVE an order
from one status to another". Those are different claims, and only the second is
worth enforcing.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

import pytest

from gulbot.models.order import OrderStatus

REPO_ROOT = Path(__file__).resolve().parents[1]

ORDER_CODE = (
    REPO_ROOT / "src/gulbot/services/orders.py",
    REPO_ROOT / "src/gulbot/bot/routers/orders.py",
)

#: Phase 2, and each one looks like two lines from inside this code.
FORBIDDEN = (
    "peak",
    "escalat",
    "confirm_order",
    "reject_order",
    "mark_delivered",
)


def code_only(path: Path) -> str:
    """Source with comments and string literals stripped.

    Both modules state in prose exactly which statuses they do NOT write, which
    a naive substring scan would read as evidence that they write them.
    """
    kept: list[str] = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(io.BytesIO(handle.read()).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


@pytest.mark.parametrize("path", ORDER_CODE, ids=lambda p: p.name)
def test_no_phase_two_machinery_leaked_in(path: Path) -> None:
    source = code_only(path).lower()
    for token in FORBIDDEN:
        assert token not in source, f"{path.name} reaches into Phase 2: {token}"


@pytest.mark.parametrize("path", ORDER_CODE, ids=lambda p: p.name)
def test_only_the_placed_status_is_ever_named(path: Path) -> None:
    """The real claim: nothing here can move an order between statuses.

    Strings are stripped, so this reads the ENUM MEMBERS the code names.
    `OrderStatus.PLACED` is the only one that may appear -- writing
    `OrderStatus.CONFIRMED` anywhere in the order path is the transition this
    checkpoint promised not to build.
    """
    source = code_only(path)
    forbidden = [
        status.name
        for status in OrderStatus
        if status is not OrderStatus.PLACED and f"OrderStatus.{status.name}" in source
    ]
    assert not forbidden, f"{path.name} names a status CP10 must not write: {forbidden}"


def test_the_service_writes_placed_and_only_placed() -> None:
    """Belt and braces on the value itself, since a literal would slip past the
    enum-member check above."""
    source = (REPO_ROOT / "src/gulbot/services/orders.py").read_text(encoding="utf-8")
    for status in OrderStatus:
        if status is OrderStatus.PLACED:
            continue
        assert f'"{status.value}"' not in source, f"the service writes {status.value!r}"


def test_nothing_in_the_order_path_updates_an_order() -> None:
    """A transition is an UPDATE. Creation is not.

    The first draft of this test banned `status =` outright and flagged the
    INSERT's own `status=PLACED` keyword -- which is the row being created, not
    moved. The claim worth enforcing is narrower and stronger: CP10 never issues
    an UPDATE against `orders` at all. Nothing can transition what nothing
    updates.
    """
    for path in ORDER_CODE:
        source = code_only(path).lower()
        assert "update ( order )" not in source, f"{path.name} updates an order row"
        assert "update (" not in source.replace("update ( order )", ""), (
            f"{path.name} issues an UPDATE; CP10 only ever inserts"
        )


def test_the_service_names_the_placed_status_exactly_once() -> None:
    """And that one mention is the insert. A second would be a transition."""
    source = code_only(REPO_ROOT / "src/gulbot/services/orders.py")
    assert source.count("OrderStatus . PLACED") == 1


def test_the_status_check_still_holds_every_future_value() -> None:
    """Guards the guard. The fence above must not be satisfied by deleting the
    other statuses from the enum -- they exist so the migration that starts
    using them is additive.
    """
    assert {s.value for s in OrderStatus} == {
        "placed",
        "confirmed",
        "delivered",
        "rejected",
        "cancelled",
    }


def test_the_order_flow_sends_no_status_updates_to_the_customer() -> None:
    """Exactly one acknowledgement, and no further messages. A 'your order is
    confirmed' key appearing here would mean the fence had moved."""
    from gulbot.i18n.catalog import CATALOG

    order_keys = {key for key in CATALOG if key.startswith("order.")}
    status_keys = {
        key
        for key in order_keys
        if any(word in key for word in ("confirmed", "delivered", "rejected"))
    }
    assert not status_keys, f"customer-facing status copy exists already: {status_keys}"
