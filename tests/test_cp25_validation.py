"""Lightweight guard tests: no DB, Redis, Bot imports or load job."""

from __future__ import annotations

import unittest

from scripts.cp25_load.validation import validate_outboxes


class OutboxValidationTests(unittest.TestCase):
    def test_missing_reminders_are_not_capacity_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "reminder_ticks"):
            validate_outboxes(
                {"reminder_ticks": [{"sent": 0}], "order_ticks": [{"sent": 100}]}, 100
            )

    def test_missing_order_pings_are_not_capacity_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "order_ticks"):
            validate_outboxes(
                {"reminder_ticks": [{"sent": 100}], "order_ticks": [{"sent": 99}]}, 100
            )

    def test_duplicate_sends_are_not_capacity_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "reminder_ticks"):
            validate_outboxes(
                {"reminder_ticks": [{"sent": 101}], "order_ticks": [{"sent": 100}]}, 100
            )

    def test_empty_ticks_are_not_capacity_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "reminder_ticks"):
            validate_outboxes({"reminder_ticks": [], "order_ticks": [{"sent": 100}]}, 100)

    def test_every_scale_and_one_failed_shop(self) -> None:
        for shops in (2, 100, 500, 1000):
            for failed in (0, 1):
                with self.subTest(shops=shops, failed=failed):
                    healthy = shops - failed
                    batches = [{"sent": min(100, healthy - i)} for i in range(0, healthy, 100)]
                    validate_outboxes({"reminder_ticks": batches, "order_ticks": batches}, healthy)


if __name__ == "__main__":
    unittest.main()
