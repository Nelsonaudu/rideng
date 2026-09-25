from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.notification_outbox import NotificationOutbox
from app.services.ride_policy import (
    ABUJA_INTERMEDIATE_STOP_WAIT_POLICY,
)


try:
    from app.services.notification_outbox import (
        cancel_pending_stop_notifications,
        schedule_stop_arrival_notifications,
        schedule_wait_ended_notification,
        schedule_wait_extension_notifications,
    )
except ImportError:
    cancel_pending_stop_notifications = None
    schedule_stop_arrival_notifications = None
    schedule_wait_ended_notification = None
    schedule_wait_extension_notifications = None


class FakeScalarResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self):
        self.rows = []
        self.flush_count = 0

    def add(self, row):
        if row not in self.rows:
            self.rows.append(row)

    def flush(self):
        self.flush_count += 1

    def commit(self):
        raise AssertionError(
            "Outbox helpers must not commit."
        )

    def _criterion(self, statement):
        criteria = list(
            statement._where_criteria
        )

        if not criteria:
            return None, None

        criterion = criteria[0]

        column_name = criterion.left.key

        value = getattr(
            criterion.right,
            "value",
            None,
        )

        return column_name, value

    def scalar(self, statement):
        column_name, value = (
            self._criterion(statement)
        )

        if column_name is None:
            return None

        for row in self.rows:
            if (
                getattr(
                    row,
                    column_name,
                    None,
                )
                == value
            ):
                return row

        return None

    def scalars(self, statement):
        column_name, value = (
            self._criterion(statement)
        )

        if column_name is None:
            return FakeScalarResult(
                self.rows
            )

        return FakeScalarResult(
            row
            for row in self.rows
            if (
                getattr(
                    row,
                    column_name,
                    None,
                )
                == value
            )
        )


class NotificationOutboxTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            schedule_stop_arrival_notifications,
            (
                "schedule_stop_arrival_notifications "
                "must exist."
            ),
        )

        self.assertIsNotNone(
            schedule_wait_extension_notifications,
            (
                "schedule_wait_extension_notifications "
                "must exist."
            ),
        )

        self.assertIsNotNone(
            cancel_pending_stop_notifications,
            (
                "cancel_pending_stop_notifications "
                "must exist."
            ),
        )

        self.assertIsNotNone(
            schedule_wait_ended_notification,
            (
                "schedule_wait_ended_notification "
                "must exist."
            ),
        )

        self.db = FakeSession()

        self.rider_id = uuid4()
        self.trip_id = uuid4()
        self.stop_id = uuid4()

        self.arrived_at = datetime(
            2026,
            9,
            25,
            12,
            0,
            0,
            tzinfo=UTC,
        )

    def schedule_arrival(self):
        return (
            schedule_stop_arrival_notifications(
                db=self.db,
                rider_id=self.rider_id,
                trip_id=self.trip_id,
                stop_id=self.stop_id,
                arrived_at=self.arrived_at,
                policy=(
                    ABUJA_INTERMEDIATE_STOP_WAIT_POLICY
                ),
            )
        )

    def test_arrival_schedules_six_warning_intents(self):
        rows = self.schedule_arrival()

        self.assertEqual(
            len(rows),
            6,
        )

        expected_offsets = [
            0,
            120,
            180,
            480,
            540,
            600,
        ]

        self.assertEqual(
            [
                int(
                    (
                        row.scheduled_for
                        - self.arrived_at
                    ).total_seconds()
                )
                for row in rows
            ],
            expected_offsets,
        )

        self.assertEqual(
            [
                row.notification_type
                for row in rows
            ],
            [
                "intermediate_stop_arrived",
                "intermediate_stop_free_wait_warning",
                "intermediate_stop_paid_wait_started",
                "intermediate_stop_exit_warning_2m",
                "intermediate_stop_exit_warning_1m",
                "intermediate_stop_wait_timeout",
            ],
        )

    def test_arrival_notifications_are_privacy_safe(self):
        rows = self.schedule_arrival()

        for row in rows:
            payload_text = str(
                row.payload
            ).lower()

            self.assertNotIn(
                "latitude",
                payload_text,
            )

            self.assertNotIn(
                "longitude",
                payload_text,
            )

            self.assertEqual(
                row.user_id,
                self.rider_id,
            )

            self.assertEqual(
                row.trip_id,
                self.trip_id,
            )

            self.assertEqual(
                row.stop_id,
                self.stop_id,
            )

            self.assertEqual(
                row.status,
                "pending",
            )

    def test_arrival_dedupe_is_stable(self):
        first = self.schedule_arrival()
        second = self.schedule_arrival()

        self.assertEqual(
            len(self.db.rows),
            6,
        )

        self.assertEqual(
            [
                row.dedupe_key
                for row in first
            ],
            [
                row.dedupe_key
                for row in second
            ],
        )

        self.assertEqual(
            len(
                {
                    row.dedupe_key
                    for row in self.db.rows
                }
            ),
            6,
        )

    def test_extension_schedules_three_intents(self):
        started_at = (
            self.arrived_at
            + timedelta(minutes=10)
        )

        rows = (
            schedule_wait_extension_notifications(
                db=self.db,
                rider_id=self.rider_id,
                trip_id=self.trip_id,
                stop_id=self.stop_id,
                extension_number=2,
                extension_started_at=started_at,
                extension_seconds=300,
                wait_rate_per_minute=(
                    Decimal("75.00")
                ),
            )
        )

        self.assertEqual(
            len(rows),
            3,
        )

        self.assertEqual(
            [
                row.scheduled_for
                for row in rows
            ],
            [
                started_at,
                started_at
                + timedelta(minutes=4),
                started_at
                + timedelta(minutes=5),
            ],
        )

        self.assertEqual(
            [
                row.notification_type
                for row in rows
            ],
            [
                "intermediate_stop_extension_started",
                "intermediate_stop_extension_warning_1m",
                "intermediate_stop_extension_ended",
            ],
        )

        for row in rows:
            self.assertIn(
                "extension:2",
                row.dedupe_key,
            )

    def test_extension_retry_does_not_duplicate(self):
        started_at = (
            self.arrived_at
            + timedelta(minutes=10)
        )

        for _ in range(2):
            schedule_wait_extension_notifications(
                db=self.db,
                rider_id=self.rider_id,
                trip_id=self.trip_id,
                stop_id=self.stop_id,
                extension_number=1,
                extension_started_at=started_at,
                extension_seconds=300,
                wait_rate_per_minute=(
                    Decimal("75.00")
                ),
            )

        self.assertEqual(
            len(self.db.rows),
            3,
        )

    def test_cancellation_changes_only_pending_future_rows(self):
        rows = self.schedule_arrival()

        now = (
            self.arrived_at
            + timedelta(minutes=4)
        )

        rows[2].status = "delivered"
        rows[2].delivered_at = (
            self.arrived_at
            + timedelta(minutes=3)
        )

        rows[3].status = "failed"

        changed = (
            cancel_pending_stop_notifications(
                db=self.db,
                stop_id=self.stop_id,
                now=now,
            )
        )

        self.assertEqual(
            changed,
            2,
        )

        self.assertEqual(
            rows[0].status,
            "pending",
        )

        self.assertEqual(
            rows[1].status,
            "pending",
        )

        self.assertEqual(
            rows[2].status,
            "delivered",
        )

        self.assertEqual(
            rows[3].status,
            "failed",
        )

        self.assertEqual(
            rows[4].status,
            "cancelled",
        )

        self.assertEqual(
            rows[5].status,
            "cancelled",
        )

        self.assertEqual(
            rows[4].cancelled_at,
            now,
        )

        self.assertEqual(
            rows[5].cancelled_at,
            now,
        )

    def test_cancellation_retry_is_idempotent(self):
        rows = self.schedule_arrival()

        now = (
            self.arrived_at
            + timedelta(minutes=4)
        )

        first = (
            cancel_pending_stop_notifications(
                db=self.db,
                stop_id=self.stop_id,
                now=now,
            )
        )

        first_cancelled_at = {
            row.dedupe_key: row.cancelled_at
            for row in rows
            if row.status == "cancelled"
        }

        second = (
            cancel_pending_stop_notifications(
                db=self.db,
                stop_id=self.stop_id,
                now=(
                    now
                    + timedelta(seconds=30)
                ),
            )
        )

        self.assertEqual(
            first,
            3,
        )

        self.assertEqual(
            second,
            0,
        )

        for row in rows:
            if row.dedupe_key in first_cancelled_at:
                self.assertEqual(
                    row.cancelled_at,
                    first_cancelled_at[
                        row.dedupe_key
                    ],
                )

    def test_wait_ended_notification_is_deduplicated(self):
        stopped_at = (
            self.arrived_at
            + timedelta(minutes=12)
        )

        first = (
            schedule_wait_ended_notification(
                db=self.db,
                rider_id=self.rider_id,
                trip_id=self.trip_id,
                stop_id=self.stop_id,
                stopped_at=stopped_at,
                final_wait_charge=(
                    Decimal("675.00")
                ),
            )
        )

        second = (
            schedule_wait_ended_notification(
                db=self.db,
                rider_id=self.rider_id,
                trip_id=self.trip_id,
                stop_id=self.stop_id,
                stopped_at=stopped_at,
                final_wait_charge=(
                    Decimal("675.00")
                ),
            )
        )

        self.assertIs(
            first,
            second,
        )

        self.assertEqual(
            len(self.db.rows),
            1,
        )

        self.assertEqual(
            first.notification_type,
            "intermediate_stop_wait_ended",
        )

        self.assertEqual(
            first.scheduled_for,
            stopped_at,
        )

        self.assertEqual(
            first.payload[
                "final_wait_charge"
            ],
            "675.00",
        )

        payload_text = str(
            first.payload
        ).lower()

        self.assertNotIn(
            "latitude",
            payload_text,
        )

        self.assertNotIn(
            "longitude",
            payload_text,
        )


if __name__ == "__main__":
    unittest.main()
