"""Alembic environment.

Uses the SYNCHRONOUS psycopg driver. Alembic's machinery is synchronous; driving
it through asyncio buys nothing and costs event-loop grief.

The target database comes from the environment, with an override used by tests
that need a throwaway database (the migration round-trip test).
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from gulbot.config import get_settings
from gulbot.db.base import Base
from gulbot.models import *  # noqa: F401,F403  (import side effect: register tables)

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: the default (True) switches off every
    # logger already imported -- here, all of gulbot's, since the models import
    # the app. Any process that ran migrations in-process, the test suite
    # included, then logged nothing at all, and a "no secret in the logs" test
    # passed only because there were no logs. tests/test_shop_tokens.py.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    override = os.environ.get("GULBOT_MIGRATION_DATABASE")
    return get_settings().database_url(database=override, driver="psycopg")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
