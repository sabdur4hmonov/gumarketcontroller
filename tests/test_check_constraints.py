"""Assert CHECK constraint CONTENT directly, because autogenerate will not.

Alembic compares check constraints by NAME. Widen an enum in the model -- add
'dead_letter' to a state list, say -- and the name is unchanged, so autogenerate
reports no difference and `test_models_match_migrations` passes while the model
and the database disagree about what is storable.

That is the second blind spot found by mutation testing rather than by reading
(the first was server defaults, at CP3.6). Both share a shape: autogenerate
notices things APPEARING and DISAPPEARING, not things CHANGING. So this module
does not ask autogenerate anything -- it reads the real constraint definitions
out of Postgres and checks them against the model.

See CONTRIBUTING.md for the running list of what autogenerate does not catch.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import CheckConstraint, create_engine, text

from gulbot.config import Settings
from gulbot.db.base import Base

#: Quoted literals inside a CHECK expression, e.g. the members of an enum list.
_LITERAL = re.compile(r"'([^']*)'")

#: Postgres renders time literals canonically, so a model's '09:00' comes back
#: as '09:00:00'. Same value, different spelling -- normalise rather than relax
#: the comparison, which would also stop it catching a real enum change.
_BARE_TIME = re.compile(r"^\d{2}:\d{2}$")


def normalise(literals: set[str]) -> set[str]:
    return {f"{lit}:00" if _BARE_TIME.match(lit) else lit for lit in literals}


def model_check_constraints() -> list[tuple[str, str, str]]:
    """(table, full_constraint_name, sqltext) for every named CHECK.

    SQLAlchemy has already applied db/base.py's naming convention by this
    point, so the name is the real one Postgres holds -- no prefixing needed.
    """
    found = []
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and constraint.name:
                name = str(constraint.name)
                assert name.startswith("ck_"), f"unconventional CHECK name: {name}"
                found.append((table.name, name, str(constraint.sqltext)))
    return sorted(found)


@pytest.fixture(scope="module")
def db_checks(settings: Settings) -> dict[str, str]:
    """Every CHECK constraint definition Postgres actually holds."""
    engine = create_engine(
        settings.database_url(database=settings.postgres_test_db, driver="psycopg")
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT c.conname, pg_get_constraintdef(c.oid) "
                    "FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE c.contype = 'c' AND n.nspname = 'public'"
                )
            ).all()
    finally:
        engine.dispose()
    return {name: definition for name, definition in rows}


def test_the_models_declare_check_constraints_at_all() -> None:
    """Guards the guard: an empty list would make everything below vacuous."""
    assert len(model_check_constraints()) >= 15


@pytest.mark.infra
def test_every_model_check_constraint_exists_in_postgres(db_checks: dict[str, str]) -> None:
    missing = [name for _table, name, _sql in model_check_constraints() if name not in db_checks]
    assert not missing, f"declared in the model but absent from the database: {missing}"


@pytest.mark.infra
def test_every_check_constraint_permits_exactly_what_the_model_says(
    db_checks: dict[str, str],
) -> None:
    """The blind spot, closed.

    Compares the literal values inside each CHECK. A state added to the model
    but not to the migration, or removed from one and not the other, fails here
    even though autogenerate sees no diff.
    """
    problems = []
    for _table, name, sqltext in model_check_constraints():
        actual = db_checks.get(name)
        if actual is None:
            continue  # covered by the test above
        expected_literals = normalise(set(_LITERAL.findall(sqltext)))
        actual_literals = normalise(set(_LITERAL.findall(actual)))
        if not expected_literals:
            continue  # a numeric or structural check, nothing to compare
        only_in_model = expected_literals - actual_literals
        only_in_db = actual_literals - expected_literals
        if only_in_model or only_in_db:
            problems.append(
                f"{name}: model-only={sorted(only_in_model)} db-only={sorted(only_in_db)}"
            )
    assert not problems, "CHECK constraints drifted:\n  " + "\n  ".join(problems)


@pytest.mark.infra
def test_the_notification_state_check_lists_every_state(db_checks: dict[str, str]) -> None:
    """Spelled out, because this one changed at CP6 and autogenerate missed it."""
    definition = db_checks["ck_scheduled_notifications_state_known"]
    for state in ("pending", "sent", "failed", "expired", "cancelled", "dead_letter"):
        assert f"'{state}'" in definition, f"{state} is not storable in the database"


@pytest.mark.infra
def test_the_message_log_status_check_lists_every_status(db_checks: dict[str, str]) -> None:
    definition = db_checks["ck_message_log_status_known"]
    for status in ("claimed", "sent", "failed", "cancelled"):
        assert f"'{status}'" in definition


@pytest.mark.infra
def test_the_product_source_check_lists_every_source(db_checks: dict[str, str]) -> None:
    """CP7's new enums get their direct guard in the same commit, per CONTRIBUTING."""
    definition = db_checks["ck_products_source_known"]
    for source in ("manual", "channel"):
        assert f"'{source}'" in definition


@pytest.mark.infra
def test_the_price_confidence_check_lists_every_level(db_checks: dict[str, str]) -> None:
    definition = db_checks["ck_products_price_confidence_known"]
    for level in ("high", "medium", "none"):
        assert f"'{level}'" in definition


@pytest.mark.infra
def test_the_price_coherence_check_exists(db_checks: dict[str, str]) -> None:
    """Structural, not an enum, so the literal comparison above cannot see it."""
    definition = db_checks["ck_products_price_matches_confidence"]
    assert "price_uzs" in definition and "price_confidence" in definition


@pytest.mark.infra
def test_the_channel_chat_check_exists(db_checks: dict[str, str]) -> None:
    """CP8's new CHECK gets its direct guard in the same commit, per CONTRIBUTING."""
    definition = db_checks["ck_products_only_channel_rows_have_a_chat_id"]
    assert "channel_chat_id" in definition and "'channel'" in definition


@pytest.mark.infra
def test_the_partial_album_index_is_actually_partial(settings: Settings) -> None:
    """A plain unique index here would be wrong AND would not be caught above:
    indexes are the third autogenerate blind spot listed in CONTRIBUTING."""
    engine = create_engine(
        settings.database_url(database=settings.postgres_test_db, driver="psycopg")
    )
    try:
        with engine.connect() as conn:
            definition = conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'uq_products_shop_media_group'"
                )
            ).scalar_one()
    finally:
        engine.dispose()
    assert "UNIQUE" in definition
    assert "media_group_id IS NOT NULL" in definition
