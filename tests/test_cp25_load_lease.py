"""Pure lease guard tests, no real database connection."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from scripts.cp25_load.load_lease import LEASE_SQL, acquire


class CapacityLeaseTests(unittest.TestCase):
    def test_competing_capacity_run_is_refused(self) -> None:
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = (False,)
        with self.assertRaisesRegex(RuntimeError, "capacity run"):
            acquire(connection)

    def test_lease_is_actually_claimed(self) -> None:
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = (True,)
        acquire(connection)
        connection.execute.assert_called_once_with(LEASE_SQL)


if __name__ == "__main__":
    unittest.main()
