"""The test database must never be a migration behind, or a migration STALE.

Two different failures, and only the first one looks like anything:

  * a migration file was ADDED -- `upgrade head` fixes it, and always did;
  * a committed migration was EDITED after being applied -- `upgrade head` does
    NOTHING, because Alembic identifies a revision by id and not by contents.
    `alembic current` still reports head. Every test then runs against a schema
    that no longer exists in the files.

The second one cost an hour at CP10: the composite-FK fix was made in a
migration the test database had already run, so the database kept the broken
foreign key and the failing test kept failing for a reason already fixed in the
source. See CONTRIBUTING.md.

`conftest.migrated_test_database` closes it by fingerprinting the migration
FILES and storing the digest on the database itself. This module proves the
fingerprint actually changes when it must -- a digest that never changed would
make the whole guard decorative.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import psycopg
import pytest
from tests import conftest
from tests.conftest import (
    FINGERPRINT_PREFIX,
    create_database,
    drop_database,
    migration_fingerprint,
    read_fingerprint,
    write_fingerprint,
)

from gulbot.config import Settings

FINGERPRINT_DB = "gulbot_fingerprint_probe"


@pytest.fixture
def versions_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway copy of migrations/versions that tests may mutate."""
    target = tmp_path / "versions"
    shutil.copytree(conftest.VERSIONS, target, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(conftest, "VERSIONS", target)
    return target


def test_the_fingerprint_is_stable_across_calls(versions_copy: Path) -> None:
    """Guards the guard from the other side: a digest that changed on every call
    would rebuild the database every run and nobody would notice for a while."""
    assert migration_fingerprint() == migration_fingerprint()


def test_editing_a_migration_changes_the_fingerprint(versions_copy: Path) -> None:
    """THE case this exists for. The filename, the revision id and the file
    count are all unchanged -- only the bytes differ, which is exactly what
    Alembic cannot see."""
    before = migration_fingerprint()
    victim = next(versions_copy.glob("ad3a69928f9b_*.py"))
    original = victim.read_bytes()
    edited = original.replace(b"ping_number >= 0", b"ping_number >= 1")
    # The first draft of this test picked `sorted(...)[-1]`, which is not the
    # file holding that string, so it replaced nothing and asserted that an
    # unchanged file produced an unchanged digest. It failed, correctly.
    assert edited != original, "the mutation did not apply; this test proves nothing"
    victim.write_bytes(edited)
    assert migration_fingerprint() != before


def test_a_comment_only_edit_still_changes_the_fingerprint(versions_copy: Path) -> None:
    """Deliberately strict. Telling a meaningful edit from a cosmetic one means
    parsing Python and reasoning about DDL; rebuilding a database takes seconds.
    The cheap side of that trade is the safe one."""
    before = migration_fingerprint()
    victim = sorted(versions_copy.glob("*.py"))[0]
    victim.write_text(victim.read_text(encoding="utf-8") + "\n# a note\n", encoding="utf-8")
    assert migration_fingerprint() != before


def test_adding_a_migration_changes_the_fingerprint(versions_copy: Path) -> None:
    before = migration_fingerprint()
    (versions_copy / "zz_new_revision.py").write_text("revision = 'zz'\n", encoding="utf-8")
    assert migration_fingerprint() != before


def test_removing_a_migration_changes_the_fingerprint(versions_copy: Path) -> None:
    before = migration_fingerprint()
    sorted(versions_copy.glob("*.py"))[-1].unlink()
    assert migration_fingerprint() != before


def test_renaming_a_migration_changes_the_fingerprint(versions_copy: Path) -> None:
    """The NAME is hashed too, not just the contents. Two files whose bodies
    were swapped would otherwise produce the same digest."""
    before = migration_fingerprint()
    victim = sorted(versions_copy.glob("*.py"))[-1]
    victim.rename(victim.with_name("aaa_" + victim.name))
    assert migration_fingerprint() != before


@pytest.mark.infra
def test_the_fingerprint_survives_a_round_trip_through_postgres(settings: Settings) -> None:
    """Stored on the DATABASE, because the database is the thing that goes stale.

    A file on disk would say the migrations are unchanged while the database
    they were applied to was dropped, recreated, or restored from a backup.
    """
    drop_database(settings, FINGERPRINT_DB)
    create_database(settings, FINGERPRINT_DB)
    try:
        assert read_fingerprint(settings, FINGERPRINT_DB) is None, "a fresh database has none"

        digest = migration_fingerprint()
        write_fingerprint(settings, FINGERPRINT_DB, digest)
        assert read_fingerprint(settings, FINGERPRINT_DB) == digest

        # And a different digest is a MISMATCH, which is what triggers a rebuild.
        assert read_fingerprint(settings, FINGERPRINT_DB) != f"{FINGERPRINT_PREFIX}deadbeef"
    finally:
        drop_database(settings, FINGERPRINT_DB)


@pytest.mark.infra
def test_a_recreated_database_reports_no_fingerprint(settings: Settings) -> None:
    """Dropping the database must lose the digest with it.

    If it did not, a rebuilt database would claim to have been built from
    migrations it never ran -- the exact false negative the guard exists to
    prevent, pointing the other way.
    """
    drop_database(settings, FINGERPRINT_DB)
    create_database(settings, FINGERPRINT_DB)
    try:
        write_fingerprint(settings, FINGERPRINT_DB, migration_fingerprint())
        assert read_fingerprint(settings, FINGERPRINT_DB) is not None
        drop_database(settings, FINGERPRINT_DB)
        create_database(settings, FINGERPRINT_DB)
        assert read_fingerprint(settings, FINGERPRINT_DB) is None
    finally:
        drop_database(settings, FINGERPRINT_DB)


@pytest.mark.infra
def test_the_test_database_carries_the_current_fingerprint(settings: Settings) -> None:
    """End to end: the session fixture wrote it, and it matches the files on disk
    RIGHT NOW. A failure here means the database this whole suite just ran
    against was built from different migrations than the repository holds."""
    assert read_fingerprint(settings, settings.postgres_test_db) == migration_fingerprint()


@pytest.mark.infra
def test_the_fingerprint_is_not_a_table(settings: Settings) -> None:
    """It must leave NO schema footprint.

    A table would be reported as drift by `test_models_match_migrations`
    forever, because autogenerate compares the whole public schema against the
    models and has no way to know this one is ours. It was a table for about
    twenty minutes, and that is exactly what happened.
    """
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname={settings.postgres_test_db}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        found = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE %s",
            ("%fingerprint%",),
        ).fetchall()
    assert not found, f"the fingerprint leaked into the schema: {found}"
