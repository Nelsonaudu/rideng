from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from uuid import uuid4

from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BooleanClauseList

from app.models.driver_assignment import DriverAssignment
from app.models.notification_outbox import NotificationOutbox
from app.models.trip import Trip
from app.models.trip_event import TripEvent
from app.models.trip_stop import TripStop
from app.models.trip_stop_wait_state import TripStopWaitState
from app.services.notification_outbox import (
    schedule_stop_arrival_notifications,
)
from app.services.ride_policy import (
    ABUJA_INTERMEDIATE_STOP_WAIT_POLICY,
)


try:
    from app.services.trip_stop_waiting import (
        authorize_current_stop_wait_extension,
        depart_current_intermediate_stop,
        exercise_current_stop_exit_right,
    )
except ImportError:
    authorize_current_stop_wait_extension = None
    depart_current_intermediate_stop = None
    exercise_current_stop_exit_right = None


class FakeScalarResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)

    def first(self):
        if not self.rows:
            return None

        return self.rows[0]


class FakeSession:
    def __init__(self, *rows):
        self.rows = list(rows)
        self.added = []
        self.flush_count = 0
        self.last_statement = None

    def add(self, row):
        if row not in self.rows:
            self.rows.append(row)

        if row not in self.added:
            self.added.append(row)

    def flush(self):
        self.flush_count += 1

    def commit(self):
        raise AssertionError(
            "Waiting lifecycle helpers must not commit."
        )

    def _entity(self, statement):
        descriptions = (
            statement.column_descriptions
        )

        if not descriptions:
            return None

        return descriptions[0].get(
            "entity"
        )

    def _right_value(self, expression):
        return getattr(
            getattr(
                expression,
                "right",
                None,
            ),
            "value",
            None,
        )

    def _matches(
        self,
        row,
        criterion,
    ):
        if isinstance(
            criterion,
            BooleanClauseList,
        ):
            return all(
                self._matches(
                    row,
                    child,
                )
                for child
                in criterion.clauses
            )

        left = getattr(
            criterion,
            "left",
            None,
        )

        key = getattr(
            left,
            "key",
            None,
        )

        if key is None:
            return True

        actual = getattr(
            row,
            key,
            None,
        )

        expected = self._right_value(
            criterion
        )

        operator = getattr(
            criterion,
            "operator",
            None,
        )

        if operator is operators.eq:
            return actual == expected

        if operator is operators.ne:
            return actual != expected

        if operator is operators.is_:
            return actual is expected

        if operator is operators.is_not:
            return actual is not expected

        return True

    def scalars(self, statement):
        self.last_statement = statement

        entity = self._entity(
            statement
        )

        rows = [
            row
            for row in self.rows
            if (
                entity is None
                or isinstance(
                    row,
                    entity,
                )
            )
        ]

        for criterion in (
            statement._where_criteria
        ):
            rows = [
                row
                for row in rows
                if self._matches(
                    row,
                    criterion,
                )
            ]

        order_clauses = list(
            statement._order_by_clauses
        )

        for clause in reversed(
            order_clauses
        ):
            element = getattr(
                clause,
                "element",
                clause,
            )

            key = getattr(
                element,
                "key",
                None,
            )

            if key is not None:
                rows.sort(
                    key=lambda row: getattr(
                        row,
                        key,
                    )
                )

        limit_clause = getattr(
            statement,
            "_limit_clause",
            None,
        )

        limit = getattr(
            limit_clause,
            "value",
            None,
        )

        if limit is not None:
            rows = rows[
                : int(limit)
            ]

        return FakeScalarResult(
            rows
        )

    def scalar(self, statement):
        return self.scalars(
            statement
        ).first()


class TripStopWaitingLifecycleTests(
    unittest.TestCase
):
    def setUp(self):
        self.assertIsNotNone(
            depart_current_intermediate_stop,
            (
                "depart_current_intermediate_stop "
                "must exist."
            ),
        )

        self.assertIsNotNone(
            authorize_current_stop_wait_extension,
            (
                "authorize_current_stop_wait_extension "
                "must exist."
            ),
        )

        self.assertIsNotNone(
            exercise_current_stop_exit_right,
            (
                "exercise_current_stop_exit_right "
                "must exist."
            ),
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

        self.ride_request_id = uuid4()
        self.trip_id = uuid4()
        self.rider_id = uuid4()
        self.driver_id = uuid4()
        self.assignment_id = uuid4()

        self.trip = Trip(
            id=self.trip_id,
            ride_request_id=(
                self.ride_request_id
            ),
            active_assignment_id=(
                self.assignment_id
            ),
            rider_id=self.rider_id,
            status="in_progress",
            agreed_fare=Decimal(
                "5750.00"
            ),
            payment_method="cash",
            matched_at=(
                self.arrived_at
                - timedelta(minutes=20)
            ),
            started_at=(
                self.arrived_at
                - timedelta(minutes=10)
            ),
        )

        self.assignment = DriverAssignment(
            id=self.assignment_id,
            ride_request_id=(
                self.ride_request_id
            ),
            driver_id=self.driver_id,
            vehicle_id=uuid4(),
            status="active",
            assigned_at=(
                self.arrived_at
                - timedelta(minutes=20)
            ),
        )

        self.stop = TripStop(
            id=uuid4(),
            ride_request_id=(
                self.ride_request_id
            ),
            trip_id=self.trip_id,
            sequence=1,
            stop_type="intermediate",
            address="Intermediate Stop",
            latitude=Decimal(
                "9.0765000"
            ),
            longitude=Decimal(
                "7.3986000"
            ),
            planned_before_matching=True,
            arrived_at=self.arrived_at,
            paid_wait_started_at=None,
            departed_at=None,
        )

        policy = (
            ABUJA_INTERMEDIATE_STOP_WAIT_POLICY
        )

        self.wait = TripStopWaitState(
            stop_id=self.stop.id,
            trip_id=self.trip.id,
            assignment_id=(
                self.assignment.id
            ),
            free_wait_seconds=(
                policy.free_wait_seconds
            ),
            wait_rate_per_minute=(
                policy.wait_rate_per_minute
            ),
            driver_exit_right_seconds=(
                policy.driver_exit_right_seconds
            ),
            extension_seconds=(
                policy.extension_seconds
            ),
            arrived_at=self.arrived_at,
            free_wait_ends_at=(
                self.arrived_at
                + timedelta(
                    seconds=(
                        policy
                        .free_wait_seconds
                    )
                )
            ),
            driver_exit_right_at=(
                self.arrived_at
                + timedelta(
                    seconds=(
                        policy
                        .driver_exit_right_seconds
                    )
                )
            ),
            current_paid_window_started_at=(
                self.arrived_at
                + timedelta(
                    seconds=(
                        policy
                        .free_wait_seconds
                    )
                )
            ),
            authorized_until=(
                self.arrived_at
                + timedelta(
                    seconds=(
                        policy
                        .driver_exit_right_seconds
                    )
                )
            ),
            accrued_billable_seconds=0,
            extension_count=0,
            final_billable_seconds=None,
            final_wait_charge=None,
            closed_at=None,
            close_reason=None,
            created_at=self.arrived_at,
            updated_at=self.arrived_at,
        )

        self.db = FakeSession(
            self.stop,
            self.wait,
        )

        schedule_stop_arrival_notifications(
            db=self.db,
            rider_id=self.rider_id,
            trip_id=self.trip.id,
            stop_id=self.stop.id,
            arrived_at=self.arrived_at,
            policy=policy,
        )

    def events(self):
        return [
            row
            for row in self.db.rows
            if isinstance(
                row,
                TripEvent,
            )
        ]

    def notices(self):
        return [
            row
            for row in self.db.rows
            if isinstance(
                row,
                NotificationOutbox,
            )
        ]

    def test_depart_during_free_wait_closes_at_zero(self):
        now = (
            self.arrived_at
            + timedelta(minutes=2)
        )

        result = (
            depart_current_intermediate_stop(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=now,
            )
        )

        self.assertEqual(
            result.final_billable_seconds,
            0,
        )

        self.assertEqual(
            result.final_wait_charge,
            Decimal("0.00"),
        )

        self.assertEqual(
            self.wait.closed_at,
            now,
        )

        self.assertEqual(
            self.wait.close_reason,
            "departed",
        )

        self.assertIsNone(
            self.wait
            .current_paid_window_started_at
        )

        self.assertIsNone(
            self.wait.authorized_until
        )

        self.assertEqual(
            self.stop.departed_at,
            now,
        )

        self.assertIsNone(
            self.stop.paid_wait_started_at
        )

    def test_depart_after_two_paid_minutes_costs_150(self):
        now = (
            self.arrived_at
            + timedelta(minutes=5)
        )

        result = (
            depart_current_intermediate_stop(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=now,
            )
        )

        self.assertEqual(
            result.final_billable_seconds,
            120,
        )

        self.assertEqual(
            result.final_wait_charge,
            Decimal("150.00"),
        )

        self.assertEqual(
            self.stop.paid_wait_started_at,
            self.wait.free_wait_ends_at,
        )

    def test_departure_cancels_only_future_warnings(self):
        now = (
            self.arrived_at
            + timedelta(minutes=5)
        )

        depart_current_intermediate_stop(
            db=self.db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            now=now,
        )

        notices = self.notices()

        cancelled = [
            row
            for row in notices
            if row.status == "cancelled"
        ]

        self.assertEqual(
            len(cancelled),
            3,
        )

        self.assertEqual(
            {
                row.notification_type
                for row in cancelled
            },
            {
                "intermediate_stop_exit_warning_2m",
                "intermediate_stop_exit_warning_1m",
                "intermediate_stop_wait_timeout",
            },
        )

        ended = [
            row
            for row in notices
            if (
                row.notification_type
                == "intermediate_stop_wait_ended"
            )
        ]

        self.assertEqual(
            len(ended),
            1,
        )

        self.assertEqual(
            ended[0].payload[
                "final_wait_charge"
            ],
            "150.00",
        )

    def test_departure_retry_is_idempotent(self):
        now = (
            self.arrived_at
            + timedelta(minutes=5)
        )

        first = (
            depart_current_intermediate_stop(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=now,
            )
        )

        event_count = len(
            self.events()
        )

        notice_count = len(
            self.notices()
        )

        second = (
            depart_current_intermediate_stop(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=(
                    now
                    + timedelta(seconds=30)
                ),
            )
        )

        self.assertEqual(
            second.final_wait_charge,
            first.final_wait_charge,
        )

        self.assertEqual(
            self.wait.closed_at,
            now,
        )

        self.assertEqual(
            self.stop.departed_at,
            now,
        )

        self.assertEqual(
            len(self.events()),
            event_count,
        )

        self.assertEqual(
            len(self.notices()),
            notice_count,
        )

    def test_extension_before_exit_right_is_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            authorize_current_stop_wait_extension(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=(
                    self.arrived_at
                    + timedelta(minutes=9)
                ),
            )

        self.assertEqual(
            self.wait.extension_count,
            0,
        )

    def test_extension_at_exit_right_opens_five_minute_window(self):
        now = (
            self.arrived_at
            + timedelta(minutes=10)
        )

        result = (
            authorize_current_stop_wait_extension(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=now,
            )
        )

        self.assertEqual(
            self.wait.accrued_billable_seconds,
            420,
        )

        self.assertEqual(
            self.wait.extension_count,
            1,
        )

        self.assertEqual(
            self.wait.current_paid_window_started_at,
            now,
        )

        self.assertEqual(
            self.wait.authorized_until,
            now
            + timedelta(minutes=5),
        )

        self.assertEqual(
            result.billable_seconds,
            420,
        )

        self.assertEqual(
            result.gross_wait_charge,
            Decimal("525.00"),
        )

        extension_notices = [
            row
            for row in self.notices()
            if (
                row.notification_type
                .startswith(
                    "intermediate_stop_extension"
                )
            )
        ]

        self.assertEqual(
            len(extension_notices),
            3,
        )

    def test_delayed_extension_does_not_back_bill_gap(self):
        now = (
            self.arrived_at
            + timedelta(minutes=12)
        )

        authorize_current_stop_wait_extension(
            db=self.db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            now=now,
        )

        self.assertEqual(
            self.wait.accrued_billable_seconds,
            420,
        )

        self.assertEqual(
            self.wait.current_paid_window_started_at,
            now,
        )

        self.assertEqual(
            self.wait.authorized_until,
            now
            + timedelta(minutes=5),
        )

    def test_exit_right_before_authorized_end_is_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            exercise_current_stop_exit_right(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=(
                    self.arrived_at
                    + timedelta(
                        minutes=9,
                        seconds=59,
                    )
                ),
            )

        self.assertIsNone(
            self.wait.closed_at
        )

    def test_exit_right_at_ten_minutes_closes_at_525(self):
        now = (
            self.arrived_at
            + timedelta(minutes=10)
        )

        result = (
            exercise_current_stop_exit_right(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=now,
            )
        )

        self.assertEqual(
            result.final_billable_seconds,
            420,
        )

        self.assertEqual(
            result.final_wait_charge,
            Decimal("525.00"),
        )

        self.assertEqual(
            self.wait.close_reason,
            "driver_exit_right",
        )

        self.assertEqual(
            self.stop.departed_at,
            now,
        )

        self.assertEqual(
            self.stop.paid_wait_started_at,
            self.wait.free_wait_ends_at,
        )

    def test_active_extension_delays_driver_exit_right(self):
        extension_at = (
            self.arrived_at
            + timedelta(minutes=10)
        )

        authorize_current_stop_wait_extension(
            db=self.db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            now=extension_at,
        )

        with self.assertRaises(
            ValueError
        ):
            exercise_current_stop_exit_right(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=(
                    extension_at
                    + timedelta(minutes=4)
                ),
            )

        self.assertIsNone(
            self.wait.closed_at
        )

    def test_full_extension_closes_at_900(self):
        extension_at = (
            self.arrived_at
            + timedelta(minutes=10)
        )

        authorize_current_stop_wait_extension(
            db=self.db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            now=extension_at,
        )

        result = (
            exercise_current_stop_exit_right(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=(
                    extension_at
                    + timedelta(minutes=5)
                ),
            )
        )

        self.assertEqual(
            result.final_billable_seconds,
            720,
        )

        self.assertEqual(
            result.final_wait_charge,
            Decimal("900.00"),
        )

        self.assertEqual(
            self.wait.extension_count,
            1,
        )

    def test_depart_mid_extension_bills_only_elapsed_extension_time(self):
        extension_at = (
            self.arrived_at
            + timedelta(minutes=10)
        )

        authorize_current_stop_wait_extension(
            db=self.db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            now=extension_at,
        )

        result = (
            depart_current_intermediate_stop(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=(
                    extension_at
                    + timedelta(seconds=90)
                ),
            )
        )

        self.assertEqual(
            result.final_billable_seconds,
            510,
        )

        self.assertEqual(
            result.final_wait_charge,
            Decimal("637.50"),
        )

    def test_old_assignment_cannot_depart_extend_or_exit(self):
        old_assignment = DriverAssignment(
            id=uuid4(),
            ride_request_id=(
                self.ride_request_id
            ),
            driver_id=uuid4(),
            vehicle_id=uuid4(),
            status="replaced",
            assigned_at=(
                self.arrived_at
                - timedelta(minutes=30)
            ),
        )

        actions = [
            (
                depart_current_intermediate_stop,
                self.arrived_at
                + timedelta(minutes=5),
            ),
            (
                authorize_current_stop_wait_extension,
                self.arrived_at
                + timedelta(minutes=10),
            ),
            (
                exercise_current_stop_exit_right,
                self.arrived_at
                + timedelta(minutes=10),
            ),
        ]

        for action, now in actions:
            with self.assertRaises(
                ValueError
            ):
                action(
                    db=self.db,
                    trip=self.trip,
                    assignment=old_assignment,
                    rider_id=self.rider_id,
                    now=now,
                )

        self.assertIsNone(
            self.wait.closed_at
        )

        self.assertEqual(
            self.wait.extension_count,
            0,
        )

    def test_closed_wait_cannot_be_extended(self):
        depart_current_intermediate_stop(
            db=self.db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            now=(
                self.arrived_at
                + timedelta(minutes=5)
            ),
        )

        with self.assertRaises(
            ValueError
        ):
            authorize_current_stop_wait_extension(
                db=self.db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                now=(
                    self.arrived_at
                    + timedelta(minutes=10)
                ),
            )

    def test_lifecycle_events_are_privacy_safe(self):
        extension_at = (
            self.arrived_at
            + timedelta(minutes=10)
        )

        authorize_current_stop_wait_extension(
            db=self.db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            now=extension_at,
        )

        exercise_current_stop_exit_right(
            db=self.db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            now=(
                extension_at
                + timedelta(minutes=5)
            ),
        )

        events = self.events()

        self.assertEqual(
            len(events),
            2,
        )

        self.assertEqual(
            [
                event.event_type
                for event in events
            ],
            [
                "intermediate_stop_wait_extended",
                "intermediate_stop_departed",
            ],
        )

        for event in events:
            text = str(
                event.event_data
            ).lower()

            self.assertNotIn(
                "latitude",
                text,
            )

            self.assertNotIn(
                "longitude",
                text,
            )


if __name__ == "__main__":
    unittest.main()
