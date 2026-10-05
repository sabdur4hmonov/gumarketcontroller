"""M1 of AUDIT_MULTI_TENANT.md: every query names its shop, in the query.

THE FINDING. Fourteen statements in the service layer reached tenant rows
through a parent key -- a `recipient_id`, an `occasion_id`, a `customer_id`, a
primary key -- that the CALLER had already checked against the shop. Every one
was safe as called. Every one encoded that safety in caller discipline rather
than in the query, which is the class of code that breaks the day a new caller
is added: a handler that forgets the check would read or rewrite another
shop's rows, and nothing would fail.

THE FENCE. In the modules the audit named, every statement that builds a
query must carry its own shop scope. Read structurally, not by text search
(CONTRIBUTING.md, "the guard that searched for a string its own helper could
never produce"): a statement counts as scoped when its AST contains

* a comparison against a `.shop_id` column -- `Occasion.shop_id == shop_id`;
* the tenancy root's own key -- `Shop.id == shop_id`;
* `shop_id` handed on by name -- `values(shop_id=...)`, `{"shop_id": ...}`,
  `sellable(shop_id)` -- to an INSERT or a helper that scopes with it.

`session.get(Model, pk)` is a primary-key fetch with no WHERE of its own, so it
is never scoped. Anything that truly needs an exception is listed in
`UNSCOPED_ON_PURPOSE` with its reason, so a new one is a decision, not a slip.

Mutation recorded at the time of writing: deleting any one predicate the fix
added turns this test red, naming the line.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import NoResultFound
from tests.bot_harness import bound_session_factory

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.occasions import discard_pending_reminders
from gulbot.services.preferences import has_answered_reminder_preferences
from gulbot.services.recipients import list_recipient_occasions

SERVICES = Path(__file__).resolve().parents[1] / "src" / "gulbot" / "services"

#: The modules M1 audited. Not the whole package: the CP16/CP17 share-page
#: services were not part of that audit and are not fenced by it.
FENCED = (
    "recipients.py",
    "occasions.py",
    "orders.py",
    "preferences.py",
    "materializer.py",
    "indexer.py",
)

QUERY_BUILDERS = frozenset({"select", "update", "delete", "insert"})
SESSION_METHODS = frozenset({"get", "delete"})

#: (module, enclosing function, what) -> why it may stay unscoped.
UNSCOPED_ON_PURPOSE: dict[tuple[str, str, str], str] = {
    ("indexer.py", "_drop_untagged", "session.delete"): (
        "an ORM delete of an instance already loaded by a shop-scoped query; "
        "it emits DELETE ... WHERE id = :pk and takes no predicate"
    ),
}


@dataclass(frozen=True)
class Unscoped:
    module: str
    function: str
    line: int
    what: str

    def __str__(self) -> str:
        return f"{self.module}:{self.line} in {self.function}(): {self.what}"


def _callee(call: ast.Call) -> str | None:
    """`select`, `update`, ... or `session.get` / `session.delete`."""
    if isinstance(call.func, ast.Name) and call.func.id in QUERY_BUILDERS:
        return call.func.id
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in SESSION_METHODS
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "session"
    ):
        return f"session.{call.func.attr}"
    return None


def _is_scope(node: ast.AST) -> bool:
    """`X.shop_id`, or the tenancy root's own key, `Shop.id`."""
    if not isinstance(node, ast.Attribute):
        return False
    if node.attr == "shop_id":
        return True
    return node.attr == "id" and isinstance(node.value, ast.Name) and node.value.id == "Shop"


def _scoped(unit: ast.AST) -> bool:
    for node in ast.walk(unit):
        if isinstance(node, ast.Compare) and any(
            _is_scope(side) for side in (node.left, *node.comparators)
        ):
            return True
        if isinstance(node, ast.keyword) and node.arg == "shop_id":
            return True
        if isinstance(node, ast.Dict) and any(
            isinstance(k, ast.Constant) and k.value == "shop_id" for k in node.keys
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and _callee(node) is None
            and any(isinstance(a, ast.Name) and a.id == "shop_id" for a in node.args)
        ):
            return True
    return False


#: Statements that contain other statements. Their own expressions (an `if`'s
#: test, a `for`'s iterable) are checked as units; their bodies are walked.
_COMPOUND_FIELDS = {
    ast.If: ("test",),
    ast.While: ("test",),
    ast.For: ("iter",),
    ast.AsyncFor: ("iter",),
    ast.With: ("items",),
    ast.AsyncWith: ("items",),
    ast.Try: (),
    ast.FunctionDef: (),
    ast.AsyncFunctionDef: (),
    ast.ClassDef: (),
}


def _units(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    """(enclosing function, smallest statement or compound header) pairs."""
    out: list[tuple[str, ast.AST]] = []

    def visit(stmts: list[ast.stmt], function: str) -> None:
        for stmt in stmts:
            fields = _COMPOUND_FIELDS.get(type(stmt))
            if fields is None:
                out.append((function, stmt))
                continue
            inner = (
                stmt.name if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef) else function
            )
            for name in fields:
                value = getattr(stmt, name)
                for part in value if isinstance(value, list) else [value]:
                    out.append((inner, part))
            for body in ("body", "orelse", "finalbody"):
                visit(getattr(stmt, body, []) or [], inner)
            for handler in getattr(stmt, "handlers", []):
                visit(handler.body, inner)

    visit(tree.body, "<module>")
    return out


def unscoped_statements() -> list[Unscoped]:
    found: list[Unscoped] = []
    for module in FENCED:
        tree = ast.parse((SERVICES / module).read_text(encoding="utf-8"))
        for function, unit in _units(tree):
            calls = [
                (node, _callee(node))
                for node in ast.walk(unit)
                if isinstance(node, ast.Call) and _callee(node) is not None
            ]
            if not calls:
                continue
            for node, what in calls:
                assert what is not None
                if (module, function, what) in UNSCOPED_ON_PURPOSE:
                    continue
                if what == "session.get" or not _scoped(unit):
                    found.append(Unscoped(module, function, node.lineno, what))
                    break
    return found


def test_every_query_in_the_audited_services_names_its_shop() -> None:
    """DEFECT IF THIS FAILS. Each line named is a query whose tenant scope
    lives in its caller. Put `Model.shop_id == shop_id` in the query."""
    assert [str(u) for u in unscoped_statements()] == []


def test_the_fence_sees_an_unscoped_query() -> None:
    """Guards the guard. A fence whose passing condition is "found nothing"
    proves nothing by passing (CONTRIBUTING.md)."""
    source = (
        "async def f(session, recipient_id):\n"
        "    await session.execute(update(Occasion).where(Occasion.recipient_id == recipient_id))\n"
        "    return await session.get(Order, 1)\n"
    )
    tree = ast.parse(source)
    flagged = [
        unit
        for _, unit in _units(tree)
        if any(isinstance(n, ast.Call) and _callee(n) for n in ast.walk(unit))
        and (not _scoped(unit) or "session.get" in ast.unparse(unit))
    ]
    assert len(flagged) == 2


def test_the_fence_accepts_each_form_of_scope() -> None:
    for line in (
        "select(Occasion).where(Occasion.shop_id == shop_id)",
        "select(Shop.channel_id).where(Shop.id == shop_id)",
        "insert(Order).values(shop_id=shop_id)",
        "insert(Tag).values([{'shop_id': p.shop_id}])",
        "select(Product).where(*sellable(shop_id))",
    ):
        assert _scoped(ast.parse(line)), line


def test_the_exceptions_are_still_where_they_say() -> None:
    """An exception for code that no longer exists is a hole waiting for a
    new statement to fall into."""
    for module, function, what in UNSCOPED_ON_PURPOSE:
        tree = ast.parse((SERVICES / module).read_text(encoding="utf-8"))
        assert any(
            name == function
            and any(isinstance(n, ast.Call) and _callee(n) == what for n in ast.walk(unit))
            for name, unit in _units(tree)
        ), (module, function, what)


# --- the same claim, against the database ----------------------------------
#
# The fence proves each query NAMES its shop. These prove what that buys: a
# caller that passes another shop's id -- the bug M1 was about, arriving
# through a new caller -- now reaches nothing instead of another shop's rows.


async def _two_shops(db: Any) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for label in ("A", "B"):
        shop = (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours) "
                    "VALUES (:n, CAST(:wh AS jsonb)) RETURNING id"
                ),
                {"n": label, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
            )
        ).scalar_one()
        customer = (
            await db.execute(
                text(
                    "INSERT INTO customers (shop_id, telegram_user_id, reminder_count) "
                    "VALUES (:s, 3001, 2) RETURNING id"
                ),
                {"s": shop},
            )
        ).scalar_one()
        recipient = (
            await db.execute(
                text(
                    "INSERT INTO recipients (shop_id, customer_id, label, type) "
                    "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
                ),
                {"s": shop, "c": customer},
            )
        ).scalar_one()
        occasion = (
            await db.execute(
                text(
                    "INSERT INTO occasions (shop_id, customer_id, recipient_id, type, kind, "
                    " label, month, day) VALUES (:s, :c, :r, 'mother', 'birthday', 'Onam', 3, 8) "
                    "RETURNING id"
                ),
                {"s": shop, "c": customer, "r": recipient},
            )
        ).scalar_one()
        await db.execute(
            text(
                "INSERT INTO scheduled_notifications (shop_id, customer_id, occasion_id, "
                " occurrence_year, offset_days, due_at_utc, channel) "
                "VALUES (:s, :c, :o, 2027, 0, now() + interval '1 day', 'telegram')"
            ),
            {"s": shop, "c": customer, "o": occasion},
        )
        out[label] = {
            "shop": shop,
            "customer": customer,
            "recipient": recipient,
            "occasion": occasion,
        }
    return out


@pytest.mark.infra
async def test_another_shops_dates_are_not_listed(db: Any) -> None:
    w = await _two_shops(db)
    async with bound_session_factory(db)() as session:
        mine = await list_recipient_occasions(
            session,
            shop_id=w["A"]["shop"],
            customer_id=w["A"]["customer"],
            recipient_id=w["A"]["recipient"],
        )
        theirs = await list_recipient_occasions(
            session,
            shop_id=w["A"]["shop"],
            customer_id=w["A"]["customer"],
            recipient_id=w["B"]["recipient"],
        )
    assert [o.id for o in mine] == [w["A"]["occasion"]]
    assert theirs == []


@pytest.mark.infra
async def test_another_shops_reminders_are_not_discarded(db: Any) -> None:
    w = await _two_shops(db)
    async with bound_session_factory(db)() as session:
        removed = await discard_pending_reminders(
            session, shop_id=w["A"]["shop"], occasion_ids=[w["B"]["occasion"]]
        )
        await session.flush()
    left = (
        await db.execute(
            text("SELECT count(*) FROM scheduled_notifications WHERE shop_id = :s"),
            {"s": w["B"]["shop"]},
        )
    ).scalar_one()
    assert (removed, left) == (0, 1)


@pytest.mark.infra
async def test_another_shops_customer_is_not_read(db: Any) -> None:
    """Loud, not quiet: a wrong-shop customer id is a bug in the caller, and
    answering "not answered yet" would hide it behind a repeated question."""
    w = await _two_shops(db)
    async with bound_session_factory(db)() as session:
        assert await has_answered_reminder_preferences(
            session, shop_id=w["B"]["shop"], customer_id=w["B"]["customer"]
        )
        try:
            answer: bool | None = await has_answered_reminder_preferences(
                session, shop_id=w["A"]["shop"], customer_id=w["B"]["customer"]
            )
        except NoResultFound:
            answer = None
    assert answer is None, "shop A read shop B's customer"
