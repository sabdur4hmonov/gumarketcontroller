"""Hold a row lock on one scheduled_notifications row, from its own process.

    python tests/lock_holder.py <row_id>

Prints `locked` once the row is held, then waits for a line on stdin and
commits. This is the deterministic stand-in for "the other worker is in phase 1
right now, holding this row": the merged-group race (CHECKPOINTS, "Found by the
gate during CP16") needs the second worker to arrive while the first holds part
of a group, and two real ticks only land in that window by luck.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg  # noqa: E402

from gulbot.config import get_settings  # noqa: E402


def main() -> None:
    row_id = int(sys.argv[1])
    s = get_settings()
    dsn = (
        f"host={s.postgres_host} port={s.postgres_port} user={s.postgres_user} "
        f"password={s.postgres_password.get_secret_value()} dbname={s.postgres_test_db}"
    )
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT id FROM scheduled_notifications WHERE id = %s FOR UPDATE", (row_id,))
        print("locked", flush=True)
        sys.stdin.readline()
        conn.commit()


if __name__ == "__main__":
    main()
