from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest


try:
    from app.services.trip_stop_waiting import (
        calculate_wait_meter,
        gross_wait_charge,
    )
except ImportError:
    calculate_wait_meter = None
    gross_wait_charge = None


UTC = timezone.utc


@dataclass
class FakeWaitState:
    arrived_at: datetime
    free_wait_ends_at: datetime
    driver_exit_right_at: datetime
    current_paid_window_started_at: datetime | None
    authorized_until: datetime | None
    accrued_billable_seconds: int
    wait_rate_per_minute: Decimal


class TripStopWaitingMathTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            calculate_wait_meter,
            "calculate_wait_meter must exist.",
        )

        self.assertIsNotNone(
            gross_wait_charge,
            "gross_wait_charge must exist.",
        )

        self.arrived_at = datetime(
            2026,
            9,
            25,
            12,
            0,
            0,
            tzinfo=UTC,
        )

    def build_initial_state(self):
        return FakeWaitState(
            arrived_at=self.arrived_at,
            free_wait_ends_at=(
                self.arrived_at
                + timedelta(seconds=180)
            ),
            driver_exit_right_at=(
                self.arrived_at
                + timedelta(seconds=600)
            ),
            current_paid_window_started_at=(
                self.arrived_at
                + timedelta(seconds=180)
            ),
            authorized_until=(
                self.arrived_at
                + timedelta(seconds=600)
            ),
            accrued_billable_seconds=0,
            wait_rate_per_minute=Decimal("75.00"),
        )

    def test_depart_before_free_wait_ends_is_zero(self):
        state = self.build_initial_state()

        snapshot = calculate_wait_meter(
            state=state,
            now=(
                self.arrived_at
                + timedelta(seconds=179)
            ),
        )

        self.assertEqual(
            snapshot.billable_seconds,
            0,
        )

        self.assertEqual(
            snapshot.gross_wait_charge,
            Decimal("0.00"),
        )

    def test_exactly_three_minutes_is_still_zero(self):
        state = self.build_initial_state()

        snapshot = calculate_wait_meter(
            state=state,
            now=(
                self.arrived_at
                + timedelta(seconds=180)
            ),
        )

        self.assertEqual(
            snapshot.billable_seconds,
            0,
        )

        self.assertEqual(
            snapshot.gross_wait_charge,
            Decimal("0.00"),
        )

    def test_five_minutes_total_means_two_paid_minutes(self):
        state = self.build_initial_state()

        snapshot = calculate_wait_meter(
            state=state,
            now=(
                self.arrived_at
                + timedelta(minutes=5)
            ),
        )

        self.assertEqual(
            snapshot.billable_seconds,
            120,
        )

        self.assertEqual(
            snapshot.gross_wait_charge,
            Decimal("150.00"),
        )

    def test_ninety_paid_seconds_costs_112_50(self):
        charge = gross_wait_charge(
            billable_seconds=90,
            rate_per_minute=Decimal("75.00"),
        )

        self.assertEqual(
            charge,
            Decimal("112.50"),
        )

    def test_no_extension_caps_initial_window_at_420_seconds(self):
        state = self.build_initial_state()

        snapshot = calculate_wait_meter(
            state=state,
            now=(
                self.arrived_at
                + timedelta(minutes=20)
            ),
        )

        self.assertEqual(
            snapshot.billable_seconds,
            420,
        )

        self.assertEqual(
            snapshot.gross_wait_charge,
            Decimal("525.00"),
        )

    def test_delayed_extension_gap_is_not_back_billed(self):
        extension_started_at = (
            self.arrived_at
            + timedelta(
                minutes=11,
                seconds=30,
            )
        )

        state = FakeWaitState(
            arrived_at=self.arrived_at,
            free_wait_ends_at=(
                self.arrived_at
                + timedelta(minutes=3)
            ),
            driver_exit_right_at=(
                self.arrived_at
                + timedelta(minutes=10)
            ),
            current_paid_window_started_at=(
                extension_started_at
            ),
            authorized_until=(
                extension_started_at
                + timedelta(minutes=5)
            ),
            accrued_billable_seconds=420,
            wait_rate_per_minute=Decimal("75.00"),
        )

        snapshot_at_extension_start = (
            calculate_wait_meter(
                state=state,
                now=extension_started_at,
            )
        )

        self.assertEqual(
            snapshot_at_extension_start.billable_seconds,
            420,
        )

        self.assertEqual(
            snapshot_at_extension_start.gross_wait_charge,
            Decimal("525.00"),
        )

        snapshot_thirty_seconds_later = (
            calculate_wait_meter(
                state=state,
                now=(
                    extension_started_at
                    + timedelta(seconds=30)
                ),
            )
        )

        self.assertEqual(
            snapshot_thirty_seconds_later.billable_seconds,
            450,
        )

        self.assertEqual(
            snapshot_thirty_seconds_later.gross_wait_charge,
            Decimal("562.50"),
        )

    def test_fractional_second_never_rounds_up(self):
        state = self.build_initial_state()

        snapshot = calculate_wait_meter(
            state=state,
            now=(
                self.arrived_at
                + timedelta(
                    minutes=5,
                    microseconds=999999,
                )
            ),
        )

        self.assertEqual(
            snapshot.billable_seconds,
            120,
        )

        self.assertEqual(
            snapshot.gross_wait_charge,
            Decimal("150.00"),
        )

    def test_exit_right_is_false_at_9_59(self):
        state = self.build_initial_state()

        snapshot = calculate_wait_meter(
            state=state,
            now=(
                self.arrived_at
                + timedelta(
                    minutes=9,
                    seconds=59,
                )
            ),
        )

        self.assertFalse(
            snapshot.exit_right_available
        )

    def test_exit_right_is_true_at_exactly_10_minutes(self):
        state = self.build_initial_state()

        snapshot = calculate_wait_meter(
            state=state,
            now=(
                self.arrived_at
                + timedelta(minutes=10)
            ),
        )

        self.assertTrue(
            snapshot.exit_right_available
        )

        self.assertTrue(
            snapshot.extension_available
        )


if __name__ == "__main__":
    unittest.main()
