import unittest

from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
)


try:
    from app.models.trip_stop_location_verification import (
        TripStopLocationVerificationState,
    )
except ImportError:
    TripStopLocationVerificationState = None


try:
    from app.models.trip_stop_wait_state import (
        TripStopWaitState,
    )
except ImportError:
    TripStopWaitState = None


try:
    from app.models.notification_outbox import (
        NotificationOutbox,
    )
except ImportError:
    NotificationOutbox = None


class TripStopModelTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            TripStopLocationVerificationState,
            (
                "TripStopLocationVerificationState "
                "must exist."
            ),
        )

        self.assertIsNotNone(
            TripStopWaitState,
            "TripStopWaitState must exist.",
        )

        self.assertIsNotNone(
            NotificationOutbox,
            "NotificationOutbox must exist.",
        )

    def foreign_key_targets(self, table):
        return {
            fk.target_fullname
            for fk in table.foreign_keys
        }

    def check_constraints(self, table):
        return {
            constraint.name: str(
                constraint.sqltext
            )
            for constraint
            in table.constraints
            if isinstance(
                constraint,
                CheckConstraint,
            )
        }

    def unique_constraints(self, table):
        return {
            constraint.name: tuple(
                column.name
                for column
                in constraint.columns
            )
            for constraint
            in table.constraints
            if isinstance(
                constraint,
                UniqueConstraint,
            )
        }

    def test_expected_table_names(self):
        self.assertEqual(
            TripStopLocationVerificationState.__tablename__,
            (
                "trip_stop_location_"
                "verification_states"
            ),
        )

        self.assertEqual(
            TripStopWaitState.__tablename__,
            "trip_stop_wait_states",
        )

        self.assertEqual(
            NotificationOutbox.__tablename__,
            "notification_outbox",
        )

    def test_stop_location_state_has_required_columns(self):
        columns = {
            column.name
            for column
            in (
                TripStopLocationVerificationState
                .__table__
                .columns
            )
        }

        expected = {
            "stop_id",
            "trip_id",
            "assignment_id",
            "last_sample_id",
            "last_latitude",
            "last_longitude",
            "last_horizontal_accuracy_m",
            "last_distance_to_stop_m",
            "last_sample_captured_at",
            "last_sample_received_at",
            "arrival_candidate_count",
            "last_arrival_candidate_at",
            "arrival_verified_at",
            "created_at",
            "updated_at",
        }

        self.assertEqual(
            columns,
            expected,
        )

        self.assertTrue(
            (
                TripStopLocationVerificationState
                .__table__
                .c
                .stop_id
                .primary_key
            )
        )

    def test_stop_location_state_has_required_foreign_keys(self):
        targets = self.foreign_key_targets(
            TripStopLocationVerificationState
            .__table__
        )

        self.assertEqual(
            targets,
            {
                "trip_stops.id",
                "trips.id",
                "driver_assignments.id",
            },
        )

    def test_wait_state_has_required_columns(self):
        columns = {
            column.name
            for column
            in TripStopWaitState.__table__.columns
        }

        expected = {
            "stop_id",
            "trip_id",
            "assignment_id",
            "free_wait_seconds",
            "wait_rate_per_minute",
            "driver_exit_right_seconds",
            "extension_seconds",
            "arrived_at",
            "free_wait_ends_at",
            "driver_exit_right_at",
            "current_paid_window_started_at",
            "authorized_until",
            "accrued_billable_seconds",
            "extension_count",
            "final_billable_seconds",
            "final_wait_charge",
            "closed_at",
            "close_reason",
            "created_at",
            "updated_at",
        }

        self.assertEqual(
            columns,
            expected,
        )

        self.assertTrue(
            (
                TripStopWaitState
                .__table__
                .c
                .stop_id
                .primary_key
            )
        )

    def test_wait_state_constraints_protect_meter_invariants(self):
        checks = self.check_constraints(
            TripStopWaitState.__table__
        )

        self.assertIn(
            "ck_trip_stop_wait_accrued_nonnegative",
            checks,
        )

        self.assertIn(
            "ck_trip_stop_wait_extension_count_nonnegative",
            checks,
        )

        self.assertIn(
            "ck_trip_stop_wait_rate_nonnegative",
            checks,
        )

        self.assertIn(
            "ck_trip_stop_wait_authorized_window",
            checks,
        )

        self.assertIn(
            "ck_trip_stop_wait_closed_window",
            checks,
        )

    def test_notification_outbox_has_required_shape(self):
        columns = {
            column.name
            for column
            in NotificationOutbox.__table__.columns
        }

        expected = {
            "id",
            "user_id",
            "trip_id",
            "stop_id",
            "notification_type",
            "dedupe_key",
            "scheduled_for",
            "payload",
            "status",
            "created_at",
            "delivered_at",
            "cancelled_at",
        }

        self.assertEqual(
            columns,
            expected,
        )

        targets = self.foreign_key_targets(
            NotificationOutbox.__table__
        )

        self.assertEqual(
            targets,
            {
                "users.id",
                "trips.id",
                "trip_stops.id",
            },
        )

    def test_notification_outbox_status_and_dedupe_are_enforced(self):
        checks = self.check_constraints(
            NotificationOutbox.__table__
        )

        self.assertIn(
            "ck_notification_outbox_status",
            checks,
        )

        status_sql = checks[
            "ck_notification_outbox_status"
        ]

        for value in (
            "pending",
            "delivered",
            "cancelled",
            "failed",
        ):
            self.assertIn(
                value,
                status_sql,
            )

        unique = self.unique_constraints(
            NotificationOutbox.__table__
        )

        self.assertEqual(
            unique.get(
                "uq_notification_outbox_dedupe_key"
            ),
            ("dedupe_key",),
        )


if __name__ == "__main__":
    unittest.main()
