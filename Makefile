# Gulbot dev commands.
#
# `make` is not installed on the Windows dev box -- use `.\make.ps1 <target>`
# there. This Makefile is the canonical definition; make.ps1 mirrors it.

PY := .venv/Scripts/python.exe

.PHONY: help venv install up down logs ps fmt lint typecheck shadow test check clean

help:
	@echo "venv install up down logs ps fmt lint typecheck shadow test check clean"

venv:
	py -3.11 -m venv .venv

install: venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

up:
	docker compose up -d --wait

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

fmt:
	$(PY) -m ruff format src tests migrations
	$(PY) -m ruff check --fix src tests migrations

lint:
	$(PY) -m ruff check src tests migrations
	$(PY) -m ruff format --check src tests migrations

typecheck:
	$(PY) -m mypy

# Registration-order gate. Walks the LIVE dispatcher; a source scan cannot
# see registration order and would not catch the bug.
shadow:
	$(PY) -m gulbot.bot.shadow_sweep

test:
	$(PY) -m pytest

# The gate. Anything that must never regress belongs here.
check: lint typecheck shadow test

clean:
	docker compose down -v
