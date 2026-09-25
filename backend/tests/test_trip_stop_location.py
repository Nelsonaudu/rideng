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
from app.models.trip_stop_location_verification import (
    TripStopLocationVerificationState,
)
from app.models.trip_stop_wait_state import (
    TripStopWaitState,
)
from app.services.location_verification import (
    LocationSample,
    LocationSampleConflictError,
    LocationSampleRejectedError,
    LocationSampleSequenceError,
)


try:
    from app.services.trip_stop_location import (
        get_current_intermediate_stop,
        process_current_stop_location,
    )
except ImportError:
    get_current_intermediate_stop = None
    process_current_stop_location = None


class FakeScalarResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)

    def first(self):
        if not self.rows:
            return None

        return self.rows[0]

    def one_or_none(self):
        if not self.rows:
            return None

        if len(self.rows) > 1:
            raise AssertionError(
                "Expected at most one row."
            )

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
            "Trip-stop service must not commit."
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
        right = getattr(
            expression,
            "right",
            None,
        )

        return getattr(
            right,
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
                    key=lambda row: (
                        getattr(
                            row,
                            key,
                        )
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


class TripStopLocationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            get_current_intermediate_stop,
            (
                "get_current_intermediate_stop "
                "must exist."
            ),
        )

        self.assertIsNotNone(
            process_current_stop_location,
            (
                "process_current_stop_location "
                "must exist."
            ),
        )

        self.now = datetime(
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
        self.vehicle_id = uuid4()
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
                self.now
                - timedelta(minutes=20)
            ),
            started_at=(
                self.now
                - timedelta(minutes=10)
            ),
        )

        self.assignment = (
            DriverAssignment(
                id=self.assignment_id,
                ride_request_id=(
                    self.ride_request_id
                ),
                driver_id=self.driver_id,
                vehicle_id=self.vehicle_id,
                status="active",
                assigned_at=(
                    self.now
                    - timedelta(minutes=20)
                ),
            )
        )

        self.pickup = self.build_stop(
            sequence=0,
            stop_type="pickup",
            latitude="9.0700000",
            longitude="7.3900000",
        )

        self.stop_1 = self.build_stop(
            sequence=1,
            stop_type="intermediate",
            latitude="9.0765000",
            longitude="7.3986000",
        )

        self.stop_2 = self.build_stop(
            sequence=2,
            stop_type="intermediate",
            latitude="9.0900000",
            longitude="7.4100000",
        )

        self.destination = self.build_stop(
            sequence=3,
            stop_type="destination",
            latitude="9.1099000",
            longitude="7.4042000",
        )

    def build_stop(
        self,
        *,
        sequence,
        stop_type,
        latitude,
        longitude,
    ):
        return TripStop(
            id=uuid4(),
            ride_request_id=(
                self.ride_request_id
            ),
            trip_id=self.trip_id,
            sequence=sequence,
            stop_type=stop_type,
            address=(
                f"Stop {sequence}"
            ),
            latitude=Decimal(
                latitude
            ),
            longitude=Decimal(
                longitude
            ),
            planned_before_matching=True,
        )

    def build_db(self):
        return FakeSession(
            self.pickup,
            self.stop_1,
            self.stop_2,
            self.destination,
        )

    def sample(
        self,
        *,
        sample_id=None,
        latitude=None,
        longitude=None,
        accuracy="10.00",
        captured_at=None,
        speed=None,
        is_mocked=None,
    ):
        return LocationSample(
            sample_id=(
                sample_id
                or uuid4()
            ),
            latitude=(
                latitude
                if latitude is not None
                else self.stop_1.latitude
            ),
            longitude=(
                longitude
                if longitude is not None
                else self.stop_1.longitude
            ),
            horizontal_accuracy_m=Decimal(
                accuracy
            ),
            captured_at=(
                captured_at
                or self.now
            ),
            reported_speed_mps=(
                Decimal(speed)
                if speed is not None
                else None
            ),
            is_mocked=is_mocked,
        )

    def test_lowest_sequence_incomplete_intermediate_stop_is_current(self):
        db = self.build_db()

        current = (
            get_current_intermediate_stop(
                db=db,
                trip_id=self.trip_id,
            )
        )

        self.assertIs(
            current,
            self.stop_1,
        )

    def test_pickup_and_destination_are_not_current_intermediate_stops(self):
        db = FakeSession(
            self.pickup,
            self.destination,
        )

        current = (
            get_current_intermediate_stop(
                db=db,
                trip_id=self.trip_id,
            )
        )

        self.assertIsNone(
            current
        )

    def test_departed_first_stop_makes_second_stop_current(self):
        self.stop_1.departed_at = (
            self.now
        )

        db = self.build_db()

        current = (
            get_current_intermediate_stop(
                db=db,
                trip_id=self.trip_id,
            )
        )

        self.assertIs(
            current,
            self.stop_2,
        )

    def test_locking_current_stop_requests_database_row_lock(self):
        db = self.build_db()

        get_current_intermediate_stop(
            db=db,
            trip_id=self.trip_id,
            lock=True,
        )

        self.assertIsNotNone(
            getattr(
                db.last_statement,
                "_for_update_arg",
                None,
            )
        )

    def test_trip_must_be_in_progress(self):
        db = self.build_db()

        self.trip.status = (
            "driver_arrived"
        )

        with self.assertRaises(
            ValueError
        ):
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(),
                now=self.now,
            )

    def test_one_good_sample_does_not_verify_stop_arrival(self):
        db = self.build_db()

        result = (
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(),
                now=self.now,
            )
        )

        self.assertEqual(
            result.stop_id,
            self.stop_1.id,
        )

        self.assertEqual(
            result.stop_sequence,
            1,
        )

        self.assertEqual(
            result.arrival_candidate_count,
            1,
        )

        self.assertFalse(
            result.arrival_verified
        )

        self.assertFalse(
            result.arrival_newly_verified
        )

        self.assertIsNone(
            self.stop_1.arrived_at
        )

        self.assertEqual(
            len(
                [
                    row
                    for row in db.rows
                    if isinstance(
                        row,
                        TripStopWaitState,
                    )
                ]
            ),
            0,
        )

    def test_two_good_samples_activate_stop_waiting_atomically(self):
        db = self.build_db()

        first_sample = self.sample(
            captured_at=self.now,
        )

        process_current_stop_location(
            db=db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            sample=first_sample,
            now=self.now,
        )

        verified_at = (
            self.now
            + timedelta(seconds=5)
        )

        second_sample = self.sample(
            captured_at=verified_at,
        )

        result = (
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=second_sample,
                now=verified_at,
            )
        )

        self.assertTrue(
            result.arrival_verified
        )

        self.assertTrue(
            result.arrival_newly_verified
        )

        self.assertEqual(
            self.stop_1.arrived_at,
            verified_at,
        )

        self.assertIsNone(
            self.stop_1.paid_wait_started_at
        )

        wait_states = [
            row
            for row in db.rows
            if isinstance(
                row,
                TripStopWaitState,
            )
        ]

        self.assertEqual(
            len(wait_states),
            1,
        )

        wait = wait_states[0]

        self.assertEqual(
            wait.stop_id,
            self.stop_1.id,
        )

        self.assertEqual(
            wait.assignment_id,
            self.assignment.id,
        )

        self.assertEqual(
            wait.free_wait_seconds,
            180,
        )

        self.assertEqual(
            wait.wait_rate_per_minute,
            Decimal("75.00"),
        )

        self.assertEqual(
            wait.driver_exit_right_seconds,
            600,
        )

        self.assertEqual(
            wait.extension_seconds,
            300,
        )

        self.assertEqual(
            wait.arrived_at,
            verified_at,
        )

        self.assertEqual(
            wait.free_wait_ends_at,
            verified_at
            + timedelta(seconds=180),
        )

        self.assertEqual(
            wait.driver_exit_right_at,
            verified_at
            + timedelta(seconds=600),
        )

        self.assertEqual(
            wait.current_paid_window_started_at,
            wait.free_wait_ends_at,
        )

        self.assertEqual(
            wait.authorized_until,
            wait.driver_exit_right_at,
        )

        notices = [
            row
            for row in db.rows
            if isinstance(
                row,
                NotificationOutbox,
            )
        ]

        self.assertEqual(
            len(notices),
            6,
        )

        events = [
            row
            for row in db.rows
            if isinstance(
                row,
                TripEvent,
            )
        ]

        self.assertEqual(
            len(events),
            1,
        )

        event = events[0]

        self.assertEqual(
            event.event_type,
            "intermediate_stop_arrived",
        )

        event_text = str(
            event.event_data
        ).lower()

        self.assertNotIn(
            "latitude",
            event_text,
        )

        self.assertNotIn(
            "longitude",
            event_text,
        )

        states = [
            row
            for row in db.rows
            if isinstance(
                row,
                TripStopLocationVerificationState,
            )
        ]

        self.assertEqual(
            len(states),
            1,
        )

        state = states[0]

        self.assertIsNone(
            state.last_latitude
        )

        self.assertIsNone(
            state.last_longitude
        )

        self.assertIsNone(
            state.last_horizontal_accuracy_m
        )

        self.assertIsNone(
            state.last_distance_to_stop_m
        )

    def test_poor_accuracy_is_rejected(self):
        db = self.build_db()

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(
                    accuracy="60.00"
                ),
                now=self.now,
            )

    def test_stale_sample_is_rejected(self):
        db = self.build_db()

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(
                    captured_at=(
                        self.now
                        - timedelta(seconds=16)
                    )
                ),
                now=self.now,
            )

    def test_future_sample_is_rejected(self):
        db = self.build_db()

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(
                    captured_at=(
                        self.now
                        + timedelta(seconds=6)
                    )
                ),
                now=self.now,
            )

    def test_mock_location_is_rejected(self):
        db = self.build_db()

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(
                    is_mocked=True
                ),
                now=self.now,
            )

    def test_out_of_order_sample_is_rejected(self):
        db = self.build_db()

        process_current_stop_location(
            db=db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            sample=self.sample(
                captured_at=self.now,
            ),
            now=self.now,
        )

        with self.assertRaises(
            LocationSampleSequenceError
        ):
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(
                    captured_at=(
                        self.now
                        - timedelta(seconds=1)
                    )
                ),
                now=(
                    self.now
                    + timedelta(seconds=1)
                ),
            )

    def test_implausible_movement_is_rejected(self):
        db = self.build_db()

        process_current_stop_location(
            db=db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            sample=self.sample(
                latitude=Decimal(
                    "9.0785000"
                ),
                captured_at=self.now,
            ),
            now=self.now,
        )

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(
                    captured_at=(
                        self.now
                        + timedelta(seconds=1)
                    )
                ),
                now=(
                    self.now
                    + timedelta(seconds=1)
                ),
            )

    def test_exact_replay_is_safe(self):
        db = self.build_db()

        sample_id = uuid4()

        first = self.sample(
            sample_id=sample_id,
            captured_at=self.now,
        )

        original = (
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=first,
                now=self.now,
            )
        )

        replay = (
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(
                    sample_id=sample_id,
                    captured_at=self.now,
                ),
                now=(
                    self.now
                    + timedelta(seconds=1)
                ),
            )
        )

        self.assertFalse(
            original.replayed
        )

        self.assertTrue(
            replay.replayed
        )

        self.assertEqual(
            replay.arrival_candidate_count,
            1,
        )

    def test_same_sample_id_with_different_data_conflicts(self):
        db = self.build_db()

        sample_id = uuid4()

        process_current_stop_location(
            db=db,
            trip=self.trip,
            assignment=self.assignment,
            rider_id=self.rider_id,
            sample=self.sample(
                sample_id=sample_id,
                captured_at=self.now,
            ),
            now=self.now,
        )

        with self.assertRaises(
            LocationSampleConflictError
        ):
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(
                    sample_id=sample_id,
                    latitude=Decimal(
                        "9.0764000"
                    ),
                    captured_at=self.now,
                ),
                now=self.now,
            )

    def test_old_assignment_cannot_authorize_stop_arrival(self):
        db = self.build_db()

        old_assignment = (
            DriverAssignment(
                id=uuid4(),
                ride_request_id=(
                    self.ride_request_id
                ),
                driver_id=uuid4(),
                vehicle_id=uuid4(),
                status="replaced",
                assigned_at=(
                    self.now
                    - timedelta(minutes=30)
                ),
            )
        )

        with self.assertRaises(
            ValueError
        ):
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=old_assignment,
                rider_id=self.rider_id,
                sample=self.sample(),
                now=self.now,
            )

        self.assertIsNone(
            self.stop_1.arrived_at
        )

    def test_new_assignment_resets_old_assignment_evidence(self):
        old_assignment_id = uuid4()

        old_state = (
            TripStopLocationVerificationState(
                stop_id=self.stop_1.id,
                trip_id=self.trip.id,
                assignment_id=(
                    old_assignment_id
                ),
                last_sample_id=uuid4(),
                last_latitude=(
                    self.stop_1.latitude
                ),
                last_longitude=(
                    self.stop_1.longitude
                ),
                last_horizontal_accuracy_m=(
                    Decimal("10.00")
                ),
                last_distance_to_stop_m=(
                    Decimal("0.00")
                ),
                last_sample_captured_at=(
                    self.now
                    - timedelta(seconds=5)
                ),
                last_sample_received_at=(
                    self.now
                    - timedelta(seconds=5)
                ),
                arrival_candidate_count=1,
                last_arrival_candidate_at=(
                    self.now
                    - timedelta(seconds=5)
                ),
            )
        )

        db = FakeSession(
            self.pickup,
            self.stop_1,
            self.stop_2,
            self.destination,
            old_state,
        )

        result = (
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(),
                now=self.now,
            )
        )

        self.assertEqual(
            old_state.assignment_id,
            self.assignment.id,
        )

        self.assertEqual(
            result.arrival_candidate_count,
            1,
        )

        self.assertFalse(
            result.arrival_verified
        )

        self.assertIsNone(
            self.stop_1.arrived_at
        )

    def test_stop_one_evidence_cannot_verify_stop_two(self):
        self.stop_1.departed_at = (
            self.now
            - timedelta(minutes=1)
        )

        stop_1_state = (
            TripStopLocationVerificationState(
                stop_id=self.stop_1.id,
                trip_id=self.trip.id,
                assignment_id=(
                    self.assignment.id
                ),
                arrival_candidate_count=1,
                last_arrival_candidate_at=(
                    self.now
                    - timedelta(seconds=5)
                ),
            )
        )

        db = FakeSession(
            self.pickup,
            self.stop_1,
            self.stop_2,
            self.destination,
            stop_1_state,
        )

        result = (
            process_current_stop_location(
                db=db,
                trip=self.trip,
                assignment=self.assignment,
                rider_id=self.rider_id,
                sample=self.sample(
                    latitude=(
                        self.stop_2.latitude
                    ),
                    longitude=(
                        self.stop_2.longitude
                    ),
                ),
                now=self.now,
            )
        )

        self.assertEqual(
            result.stop_id,
            self.stop_2.id,
        )

        self.assertEqual(
            result.arrival_candidate_count,
            1,
        )

        self.assertFalse(
            result.arrival_verified
        )

        stop_2_states = [
            row
            for row in db.rows
            if (
                isinstance(
                    row,
                    TripStopLocationVerificationState,
                )
                and row.stop_id
                == self.stop_2.id
            )
        ]

        self.assertEqual(
            len(stop_2_states),
            1,
        )

        self.assertEqual(
            stop_1_state.arrival_candidate_count,
            1,
        )


if __name__ == "__main__":
    unittest.main()
