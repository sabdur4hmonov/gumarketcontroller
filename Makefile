# Gulbot dev commands.
#
# `make` is not installed on the Windows dev box -- use `.\make.ps1 <target>`
# there. This Makefile is the canonical definition; make.ps1 mirrors it.

PY := .venv/Scripts/python.exe

.PHONY: help venv install up down logs ps fmt lint typecheck test check clean

help:
	@echo "venv install up down logs ps fmt lint typecheck test check clean"

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
	$(PY) -m ruff format src tests
	$(PY) -m ruff check --fix src tests

lint:
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

typecheck:
	$(PY) -m mypy

test:
	$(PY) -m pytest

# The gate. Anything that must never regress belongs here.
# CP2 adds the handler-shadowing sweep to this target.
check: lint typecheck test

clean:
	docker compose down -v
