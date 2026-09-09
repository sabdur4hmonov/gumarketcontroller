"""The scope fence: exactly ONE module may move an order between statuses.

CP10 wrote this fence to say NOTHING may. CP13 makes the shop's order card
actionable, so one module now has to -- and the fence is NARROWED rather
than deleted, because the difference between those two is the difference
between "we chose to allow this" and "someone turned off the alarm".

What it still forbids, and why each one is a plausible-looking two-line
addition to the module that just wrote the order:

  * the ORDER PATH -- the FSM and the submit service -- still writes only
    'placed' and still issues no UPDATE against `orders` at all. A customer
    flow that could confirm its own order is not a feature, it is a bug
    nobody would notice until a shop asked why everything was accepted.
  * `delivered`, peak mode and the escalation ladder are still Phase 2, and
    still named in docs/CHECKPOINTS.md rather than half-built here.

The five statuses have been in the CHECK since CP10a on purpose, so the
migration that began using two of them was additive. The fence is not "the
words must not appear in the schema", it is "only one module may move an
order", which is a different claim and the one worth enforcing.
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import pytest

from gulbot.models.order import OrderStatus

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The CUSTOMER-facing order path. Still forbidden to move a status.
ORDER_CODE = (
    REPO_ROOT / "src/gulbot/services/orders.py",
    REPO_ROOT / "src/gulbot/bot/routers/orders.py",
)

#: The ONE module allowed to. Named here so the exception is a list of one
#: rather than an absence of enforcement.
TRANSITION_MODULE = REPO_ROOT / "src/gulbot/services/order_status.py"

#: Still Phase 2, and each one looks like two lines from inside this code.
#: `confirm_order` and `reject_order` have LEFT this list -- they exist now,
#: in `order_status.py` -- but the customer path still must not call them,
#: which the UPDATE check below enforces.
FORBIDDEN = (
    "peak",
    "escalat",
    "mark_delivered",
)


def names(status: OrderStatus) -> str:
    """How a status reference LOOKS in `code_only` output.

    `code_only` joins tokens with spaces, so `OrderStatus.CONFIRMED` is
    stored as `OrderStatus . CONFIRMED`. Searching for the unspaced form
    matches nothing, ever -- which is exactly what
    `test_only_the_placed_status_is_ever_named` did from CP10a until CP13.
    It passed the whole time and checked nothing.

    Found while adding a NEW test with the same bug: it reported zero
    transition modules in a codebase that had just gained one.
    """
    return f"OrderStatus . {status.name}"


#: Calls whose arguments are being COMPARED against, not written. A status
#: named inside one of these is code asking a question about existing rows.
#: CP9's daily cap has excluded cancelled and rejected orders exactly this
#: way since long before anything could transition an order.
READ_CALLS = frozenset({"where", "having", "filter", "in_", "notin_", "is_", "isnot"})

#: Calls that put a value INTO a row.
WRITE_CALLS = frozenset({"values"})


def statuses_written(path: Path) -> set[str]:
    """The statuses this module puts INTO a row.

    NAMING a status is not MOVING an order to it, and the first version of
    this fence could not tell the two apart -- it read CP9's daily-cap filter
    (`status.notin_([CANCELLED, REJECTED])`) as evidence that the customer
    path transitions orders. It does not; it declines to count dead ones
    against a cap.

    So the claim is structural rather than textual: walk the AST, find every
    `OrderStatus.X`, and climb to the nearest construct that settles which
    side of the fence it is on.
    """
    tree = ast.parse(path.read_bytes())
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "OrderStatus"
        and _is_a_write(node, parents)
    }


def statuses_named(path: Path) -> set[str]:
    """Every status this module mentions at all, however it uses it.

    The coarse question, on purpose: `statuses_written` answers "does this put
    a status into a row", which is the sharp claim about the customer order
    path. This one answers "does this module know outcomes exist", which is
    the claim about how far that knowledge has spread.
    """
    tree = ast.parse(path.read_bytes())
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "OrderStatus"
    }


def _is_a_write(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Climb until something settles it.

    UNRECOGNISED CONSTRUCTS COUNT AS WRITES. A fence whose default is
    "probably fine" is the kind that quietly stops holding; this one trips
    loudly and someone classifies the new construct on purpose.
    """
    current: ast.AST | None = node
    while (current := parents.get(current)) is not None:
        if isinstance(current, ast.Compare):
            return False
        if isinstance(current, ast.Call):
            func = current.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if called in READ_CALLS:
                return False
            if called in WRITE_CALLS:
                return True
        if isinstance(current, ast.keyword | ast.Assign | ast.Dict):
            return True
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.Module):
            return True
    return True


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
def test_the_order_path_writes_only_the_placed_status(path: Path) -> None:
    """The customer path may ASK about any status and WRITE only one.

    This replaces CP10a's `test_only_the_placed_status_is_ever_named`, which
    searched `code_only` output for the UNSPACED `OrderStatus.CONFIRMED` while
    `code_only` emits `OrderStatus . CONFIRMED`. It therefore matched nothing
    from CP10a until CP13 and passed for free the entire time.

    Repairing the spacing made it fail -- correctly, on CP9's daily-cap filter
    -- which showed the claim itself was wrong as well as unenforced. "Names"
    was never the invariant. "Writes" is.
    """
    forbidden = statuses_written(path) - {OrderStatus.PLACED.name}
    assert not forbidden, f"{path.name} writes a status it must not: {sorted(forbidden)}"


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


def test_only_the_transition_module_updates_an_order_row() -> None:
    """The same claim as above, reached a different way.

    A transition is an UPDATE, so the modules that may UPDATE `orders` and the
    modules that may write a status have to be the same one module. Two
    independent routes to one answer, because the status scan reads names and
    this reads the operation -- a bypass would have to fool both.
    """
    updaters = [
        path
        for path in sorted((REPO_ROOT / "src").rglob("*.py"))
        if "update ( Order )" in code_only(path)
    ]
    assert updaters == [TRANSITION_MODULE], (
        f"only the transition module may UPDATE an order; found {updaters}"
    )


def test_the_service_names_the_placed_status_exactly_once() -> None:
    """And that one mention is the insert. A second would be a transition."""
    source = code_only(REPO_ROOT / "src/gulbot/services/orders.py")
    assert source.count(names(OrderStatus.PLACED)) == 1


def test_only_the_named_modules_reason_about_order_outcomes() -> None:
    """Not "one module may transition" -- that is the UPDATE test above. This
    is the blast radius: WHICH modules know an order can be anything other
    than placed.

    Four do, and each for a stated reason (`models/order.py` DEFINES the
    enum rather than referencing it, so it does not appear here):

      * `services/order_status.py`  moves an order between them.
      * `services/order_notify.py`  maps an outcome to what the customer reads.
      * `routers/admin_orders.py`   is where the shop taps the button.
      * `services/orders.py`   asks about them -- CP9's daily cap does not
        count cancelled or rejected orders. It still WRITES only 'placed',
        which `test_the_order_path_writes_only_the_placed_status` pins.

    A fifth module appearing here is not necessarily wrong. It is a decision,
    and this test is what makes someone make it on purpose -- which is the
    entire difference between a fence and a comment.
    """
    allowed = {
        REPO_ROOT / "src/gulbot/services/orders.py",
        REPO_ROOT / "src/gulbot/services/order_notify.py",
        REPO_ROOT / "src/gulbot/bot/routers/admin_orders.py",
        TRANSITION_MODULE,
    }
    aware = {
        path
        for path in (REPO_ROOT / "src").rglob("*.py")
        if statuses_named(path) - {OrderStatus.PLACED.name}
    }
    assert aware == allowed, (
        f"unexpected: {sorted(aware - allowed)}; no longer present: {sorted(allowed - aware)}"
    )


def test_the_transition_module_actually_guards_its_updates() -> None:
    """The exception is only safe because every transition is a
    compare-and-swap. A bare UPDATE there would let two admins both succeed
    and the customer be messaged twice."""
    source = code_only(TRANSITION_MODULE)
    assert "Order . status == OrderStatus . PLACED . value" in source, (
        "a transition must be guarded on the order still being placed"
    )


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


#: The only outcomes a customer is told about. CP13 added both, deliberately.
#: `delivered` is NOT here: nothing marks an order delivered, so copy for it
#: would be a promise the product does not keep.
CUSTOMER_STATUS_COPY = {"order.status.confirmed", "order.status.rejected"}


def test_the_customer_hears_about_exactly_two_outcomes() -> None:
    """CP10 asserted there was NO customer-facing status copy. That was true
    then and is the thing CP13 was pulled forward to change -- an order sitting
    unconfirmed while the customer assumes it was accepted is the silence this
    checkpoint exists to remove.

    So the claim narrows to a whitelist rather than being deleted. A third key
    appearing here is either a status nothing sets, or a message someone added
    without deciding it should exist.
    """
    from gulbot.i18n.catalog import CATALOG

    status_keys = {
        key
        for key in CATALOG
        if key.startswith("order.")
        and any(word in key for word in ("confirmed", "delivered", "rejected"))
    }
    assert status_keys == CUSTOMER_STATUS_COPY, (
        f"customer-facing status copy changed: {sorted(status_keys)}"
    )


def test_every_outcome_the_customer_hears_about_has_copy_in_every_language() -> None:
    """The notifier looks the key up by status. A status in its map with no
    catalog entry sends the customer the literal key -- `t` returns the key
    rather than raising, which is right for a missing button label and wrong
    for the message telling someone their order was refused."""
    from gulbot.i18n.catalog import CATALOG, LANGUAGES
    from gulbot.services.order_notify import OUTCOME_COPY

    for status, key in OUTCOME_COPY.items():
        assert key in CATALOG, f"{status.value} has no copy"
        for lang in LANGUAGES:
            assert CATALOG[key].get(lang, "").strip(), f"{key} is empty in {lang}"
