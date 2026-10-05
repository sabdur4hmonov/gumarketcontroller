"""L1 of AUDIT_MULTI_TENANT.md: the dev and ops tools name the shop they act on.

THE FINDING. Written while there was one shop, the tools assumed it:

* `scripts/live_browse.py` and `scripts/live_order.py` hardcoded `shop_id = 1`
  in SQL and in Python, and spoke through the process `BOT_TOKEN`;
* `scripts/live_confirm.py` took "the first shop" -- `ORDER BY id LIMIT 1`;
* `gulbot.cli.force_reminder` found the customer, the date and the person by
  primary key alone, with no shop anywhere in the lookup, and filtered
  `--list` by shop in Python after loading every shop.

Against a fleet database each of those acts on whichever shop happens to be
first, or on one the operator never meant, and the scripts would post as the
pilot's bot into another shop's chats.

THE FIX. Every tool takes `--shop-id`, refuses to act without it, scopes its
queries by it, and speaks through that shop's own bot. `verify_group.py` (C4)
and `live_pages.py` (CP16) already did; they are fenced here too so none of
them drifts back.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory

import gulbot.cli.force_reminder as force_reminder
from gulbot.models.shop import DEFAULT_WORKING_HOURS

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
TOOLS = sorted(SCRIPTS.glob("*.py")) + [
    Path(force_reminder.__file__),  # type: ignore[arg-type]
]

#: A shop picked by position or by a literal id, in SQL.
HARDCODED_SHOP_SQL = re.compile(
    r"shop_id\s*=\s*\d"
    r"|shops\s+WHERE\s+id\s*=\s*\d"
    r"|FROM\s+shops\s+ORDER\s+BY\s+id\s+LIMIT\s+1"
    r"|\(\s*shop_id\b[^)]*\)\s*VALUES\s*\(\s*\d",
    re.IGNORECASE,
)


def _hardcoded_shops(path: Path) -> list[str]:
    found: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "shop_id"
            and isinstance(node.value, ast.Constant)
        ):
            found.append(f"{path.name}:{node.value.lineno}: shop_id={node.value.value!r}")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and HARDCODED_SHOP_SQL.search(node.value)
        ):
            found.append(f"{path.name}:{node.lineno}: {node.value.strip()[:70]!r}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_bot"
        ):
            found.append(f"{path.name}:{node.lineno}: build_bot() -- the process bot")
    return found


@pytest.mark.parametrize("path", TOOLS, ids=lambda p: p.name)
def test_no_tool_picks_a_shop_for_the_operator(path: Path) -> None:
    """DEFECT IF THIS FAILS: a literal shop id, the first shop by position, or
    the process bot speaking for whichever shop the tool is acting on."""
    assert _hardcoded_shops(path) == []


def test_the_fence_sees_each_form(tmp_path: Path) -> None:
    """Guards the guard: each shape it exists to catch, caught."""
    sample = (
        "conn.execute('SELECT 1 FROM customers WHERE shop_id = 1')\n"
        "conn.execute('SELECT id FROM shops ORDER BY id LIMIT 1')\n"
        "conn.execute('SELECT group_chat_id FROM shops WHERE id = 1')\n"
        "conn.execute('INSERT INTO t (shop_id, order_id) VALUES (1, %s)')\n"
        "build_dispatcher(shop_id=1)\n"
        "bot = build_bot()\n"
    )
    probe = tmp_path / "probe.py"
    probe.write_text(sample, encoding="utf-8")
    assert len(_hardcoded_shops(probe)) == 6


# --- each script refuses to run without a shop ------------------------------


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _exit_code(parse: Any, argv: list[str]) -> int | str | None:
    try:
        parse(argv)
    except SystemExit as stopped:
        return stopped.code
    return None


@pytest.mark.parametrize(
    ("script", "argv"),
    [
        ("live_browse", []),
        ("live_order", ["--product", "16"]),
        ("live_confirm", ["--customer-tg", "1", "--confirm"]),
    ],
)
def test_a_script_without_a_shop_stops_at_the_parser(script: str, argv: list[str]) -> None:
    module = _load(script)
    assert _exit_code(module.build_parser().parse_args, argv) == 2
    assert _exit_code(module.build_parser().parse_args, [*argv, "--shop-id", "7"]) is None


def test_force_reminder_will_not_send_without_a_shop() -> None:
    """DEFECT IF THIS FAILS. `--shop-id` existed only to narrow `--list`; the
    send path ignored it, so a customer id was enough to send as any shop."""
    send = ["--customer-id", "3", "--occasion-id", "7"]
    assert _exit_code(force_reminder._parse_args, send) == 2
    assert _exit_code(force_reminder._parse_args, ["--shop-id", "1", *send]) is None
    assert _exit_code(force_reminder._parse_args, ["--list"]) is None, "--list may span shops"


# --- force_reminder looks everything up inside that shop ------------------


@pytest.fixture
def on_the_test_connection(db: AsyncConnection, monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def factory() -> AsyncIterator[Any]:
        yield bound_session_factory(db)

    monkeypatch.setattr(force_reminder, "task_session_factory", factory)


async def _shop_with_a_date(db: AsyncConnection, name: str, tg: int) -> dict[str, int]:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES (:n, CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"),
            {"s": shop, "t": tg},
        )
    ).scalar_one()
    recipient = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, :l, 'mother') RETURNING id"
            ),
            {"s": shop, "c": customer, "l": f"Onam of {name}"},
        )
    ).scalar_one()
    occasion = (
        await db.execute(
            text(
                "INSERT INTO occasions (shop_id, customer_id, recipient_id, type, kind, "
                " label, month, day) VALUES (:s, :c, :r, 'mother', 'birthday', 'x', 3, 8) "
                "RETURNING id"
            ),
            {"s": shop, "c": customer, "r": recipient},
        )
    ).scalar_one()
    return {"shop": shop, "customer": customer, "occasion": occasion}


@pytest.mark.infra
async def test_force_reminder_refuses_another_shops_customer(
    db: AsyncConnection, on_the_test_connection: None
) -> None:
    a = await _shop_with_a_date(db, "A", 5_001)
    b = await _shop_with_a_date(db, "B", 5_002)
    with pytest.raises(SystemExit) as refused:
        await force_reminder._render(a["shop"], b["customer"], b["occasion"], 0)
    # The FIRST check names the actual problem: this customer is not in shop A.
    assert str(refused.value.code) == f"no customer id={b['customer']} in shop {a['shop']}"

    text_, _, chat_id, shop_id = await force_reminder._render(
        b["shop"], b["customer"], b["occasion"], 0
    )
    assert (chat_id, shop_id) == (5_002, b["shop"])
    assert "Eslatma" in text_, "the real reminder was not rendered"


@pytest.mark.infra
async def test_force_reminder_lists_one_shop_from_sql(
    db: AsyncConnection, on_the_test_connection: None, capsys: pytest.CaptureFixture[str]
) -> None:
    a = await _shop_with_a_date(db, "A", 5_001)
    await _shop_with_a_date(db, "B", 5_002)
    await force_reminder._list(a["shop"], None)
    out = capsys.readouterr().out
    assert f"shop id={a['shop']}" in out
    assert "'B'" not in out and "5002" not in out
