"""The product's name is one setting (CP19).

The brand is not decided yet. Every place a customer, a shop owner or the
platform admin can READ the name takes it from `Settings.brand_name`
(`BRAND_NAME` in the environment), through `gulbot.brand.brand_name()`. So the
day it is decided is a one-line change, and this file is what keeps it one
line: the name typed anywhere else fails the build.

What counts as "typed anywhere else":

- a Python string literal in `src/gulbot` holding the name in any casing but
  all-lowercase. All-lowercase `gulbot` is the CODE's namespace -- the package,
  logger and task names, Redis keys, the pages' request header -- which no user
  reads and which renaming would break (a Celery task name in a queue, a
  calendar UID a phone already holds);
- any value in the bot's catalog, in ANY casing, because all of it is read;
- any Jinja template, in any casing, outside `{# comments #}`;
- the pages' JavaScript and CSS, outside comments, in any casing but
  all-lowercase (the request header token is code, not copy).

Docstrings and comments are for developers and are not scanned. License records
(`*.md`, `*.txt` under static/) are provenance -- who wrote a tune, and when --
and stay as written.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

import gulbot
from gulbot import brand
from gulbot.config import Settings
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.web import render

SRC = Path(gulbot.__file__).resolve().parent
WEB = SRC / "web"

#: The working name, in every spelling a person might type it. The Uzbek
#: copy attaches suffixes ("Gulbotga"), so there is no word boundary after it.
NAME = re.compile(r"gul[\s_-]?bot", re.IGNORECASE)

PLACEHOLDER = "{brand}"


def _shouting(text: str) -> list[str]:
    """Occurrences of the name that are not the all-lowercase code namespace."""
    return [m.group(0) for m in NAME.finditer(text) if m.group(0) != m.group(0).lower()]


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _the_one_place(tree: ast.AST) -> set[int]:
    """The default of `Settings.brand_name` in config.py -- the only literal
    allowed to hold the name."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "brand_name"
            and isinstance(node.value, ast.Constant)
        ):
            ids.add(id(node.value))
    return ids


def python_literals() -> Iterator[tuple[str, int, str]]:
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstring_nodes(tree)
        if path.name == "config.py":
            skip |= _the_one_place(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip
            ):
                yield str(path.relative_to(SRC)), node.lineno, node.value


def _without(pattern: str, text: str) -> str:
    return re.sub(pattern, " ", text, flags=re.DOTALL)


def template_texts() -> Iterator[tuple[str, str]]:
    for path in sorted((WEB / "templates").rglob("*.html")):
        yield str(path.relative_to(SRC)), _without(r"\{#.*?#\}", path.read_text("utf-8"))


def script_texts() -> Iterator[tuple[str, str]]:
    for path in sorted((WEB / "static").rglob("*")):
        if path.suffix not in {".js", ".css"}:
            continue
        text = _without(r"/\*.*?\*/", path.read_text("utf-8"))
        text = re.sub(r"(?m)^\s*//.*$", " ", text)
        yield str(path.relative_to(SRC)), text


# --- the guard ----------------------------------------------------------------


def test_the_scan_sees_what_it_claims_to_see() -> None:
    """Guards the guard: an empty walk would pass everything below."""
    assert sum(1 for _ in python_literals()) > 2000
    assert len(list(template_texts())) >= 15
    assert len(list(script_texts())) >= 20
    assert len(CATALOG) > 300


def test_no_python_literal_types_the_name() -> None:
    found = [
        f"{where}:{line}: {_shouting(text)}"
        for where, line, text in python_literals()
        if _shouting(text)
    ]
    assert not found, "the brand typed outside Settings.brand_name:\n" + "\n".join(found)


def test_no_catalog_string_types_the_name() -> None:
    found = [
        f"{key}.{lang}"
        for key, entry in CATALOG.items()
        for lang, text in entry.items()
        if NAME.search(text)
    ]
    assert not found, f"use {PLACEHOLDER} instead: {found}"


def test_no_template_types_the_name() -> None:
    found = [where for where, text in template_texts() if NAME.search(text)]
    assert not found, f"use {{{{ brand() }}}} instead: {found}"


def test_no_page_script_or_stylesheet_types_the_name() -> None:
    found = [where for where, text in script_texts() if _shouting(text)]
    assert not found, found


# --- and the one place reaches every surface -----------------------------------


@pytest.fixture
def renamed(monkeypatch: pytest.MonkeyPatch) -> str:
    """The brand changed in the one place, and only there."""
    monkeypatch.setattr(brand, "get_settings", lambda: Settings(brand_name="Zarbot"))
    return "Zarbot"


def test_the_setting_defaults_to_the_working_name() -> None:
    assert Settings().brand_name == "Gulbot"


def test_the_name_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAND_NAME", "Lolabot")
    assert Settings().brand_name == "Lolabot"


@pytest.mark.parametrize("bad", ["", "   ", "<b>x</b>", "a&b", "{x}", "x" * 41])
def test_a_name_that_would_break_a_message_is_refused(bad: str) -> None:
    """Bot messages are Telegram HTML and the catalog is str.format'ed."""
    with pytest.raises(ValueError, match="brand_name"):
        Settings(brand_name=bad)


def _branded_keys() -> list[tuple[str, str]]:
    return [
        (key, lang)
        for key, entry in CATALOG.items()
        for lang, text in entry.items()
        if PLACEHOLDER in text
    ]


def test_every_bot_text_that_names_the_product_follows_the_setting(renamed: str) -> None:
    keys = _branded_keys()
    assert len(keys) >= 10, keys  # help, welcome, onboarding, group test, music -- uz/ru/en
    for key, lang in keys:
        text = t(key, lang)
        assert renamed in text, (key, lang)
        assert PLACEHOLDER not in text, (key, lang)


def test_a_branded_text_with_its_own_placeholders_still_formats(renamed: str) -> None:
    for key, lang in _branded_keys():
        text = t(key, lang, name="Aziz")
        assert PLACEHOLDER not in text, (key, lang)


def test_the_admin_panel_title_follows_the_setting(renamed: str) -> None:
    html = render.render("admin/login.html", {"token": "x" * 43})
    assert f"<title>{renamed}" in html
    assert f"{renamed} boshqaruv paneli" in html


def test_the_gone_page_names_the_product_when_there_is_no_shop(renamed: str) -> None:
    from gulbot.web.app import _gone

    body = _gone().text or ""
    assert renamed in body


def test_the_calendar_file_names_the_product(renamed: str) -> None:
    from gulbot.web.render import calendar_product_id

    assert calendar_product_id() == f"-//{renamed}//Taklifnoma//UZ"
