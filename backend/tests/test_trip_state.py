from datetime import UTC, datetime
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.trip import Trip
from app.models.trip_event import TripEvent
from app.services.trip_state import (
    TripArrivalVerificationError,
    TripTransitionError,
    transition_trip,
)


class RecordingSession:
    def __init__(self):
        self.added = []
        self.flush_count = 0

    def add(
        self,
        item,
    ):
        self.added.append(
            item
        )

    def flush(
        self,
    ):
        self.flush_count += 1


class TripStateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(
            2026,
            9,
            16,
            23,
            0,
            tzinfo=UTC,
        )

        self.actor_user_id = uuid4()

    def build_trip(
        self,
        *,
        status: str,
    ) -> Trip:
        return Trip(
            id=uuid4(),
            ride_request_id=uuid4(),
            active_assignment_id=uuid4(),
            rider_id=uuid4(),
            status=status,
            agreed_fare=Decimal(
                "5750.00"
            ),
            payment_method="cash",
            matched_at=self.now,
        )

    def test_matched_can_move_to_driver_arriving(self):
        db = RecordingSession()

        trip = self.build_trip(
            status="matched",
        )

        transition_trip(
            db=db,
            trip=trip,
            target_status=(
                "driver_arriving"
            ),
            actor_user_id=(
                self.actor_user_id
            ),
            event_type=(
                "driver_arriving"
            ),
            now=self.now,
        )

        self.assertEqual(
            trip.status,
            "driver_arriving",
        )

        self.assertEqual(
            trip.driver_arriving_at,
            self.now,
        )

        self.assertEqual(
            len(db.added),
            1,
        )

        event = db.added[0]

        self.assertIsInstance(
            event,
            TripEvent,
        )

        self.assertEqual(
            event.event_type,
            "driver_arriving",
        )

        self.assertEqual(
            event.event_data[
                "from_status"
            ],
            "matched",
        )

        self.assertEqual(
            event.event_data[
                "to_status"
            ],
            "driver_arriving",
        )

    def test_arrival_requires_verified_arrival(self):
        db = RecordingSession()

        trip = self.build_trip(
            status="driver_arriving",
        )

        with self.assertRaises(
            TripArrivalVerificationError
        ):
            transition_trip(
                db=db,
                trip=trip,
                target_status=(
                    "driver_arrived"
                ),
                actor_user_id=(
                    self.actor_user_id
                ),
                event_type=(
                    "driver_arrived"
                ),
                arrival_verified=False,
                now=self.now,
            )

        self.assertEqual(
            trip.status,
            "driver_arriving",
        )

        self.assertEqual(
            len(db.added),
            0,
        )

    def test_verified_arrival_can_transition(self):
        db = RecordingSession()

        trip = self.build_trip(
            status="driver_arriving",
        )

        transition_trip(
            db=db,
            trip=trip,
            target_status=(
                "driver_arrived"
            ),
            actor_user_id=(
                self.actor_user_id
            ),
            event_type=(
                "driver_arrived"
            ),
            arrival_verified=True,
            now=self.now,
        )

        self.assertEqual(
            trip.status,
            "driver_arrived",
        )

        self.assertEqual(
            trip.arrived_at,
            self.now,
        )

        self.assertEqual(
            len(db.added),
            1,
        )

    def test_matched_cannot_skip_to_completed(self):
        db = RecordingSession()

        trip = self.build_trip(
            status="matched",
        )

        with self.assertRaises(
            TripTransitionError
        ):
            transition_trip(
                db=db,
                trip=trip,
                target_status=(
                    "completed"
                ),
                actor_user_id=(
                    self.actor_user_id
                ),
                event_type=(
                    "trip_completed"
                ),
                now=self.now,
            )

    def test_completed_trip_cannot_restart(self):
        db = RecordingSession()

        trip = self.build_trip(
            status="completed",
        )

        with self.assertRaises(
            TripTransitionError
        ):
            transition_trip(
                db=db,
                trip=trip,
                target_status=(
                    "driver_arriving"
                ),
                actor_user_id=(
                    self.actor_user_id
                ),
                event_type=(
                    "driver_arriving"
                ),
                now=self.now,
            )

    def test_cancelled_trip_cannot_progress(self):
        db = RecordingSession()

        trip = self.build_trip(
            status="rider_cancelled",
        )

        with self.assertRaises(
            TripTransitionError
        ):
            transition_trip(
                db=db,
                trip=trip,
                target_status=(
                    "driver_arriving"
                ),
                actor_user_id=(
                    self.actor_user_id
                ),
                event_type=(
                    "driver_arriving"
                ),
                now=self.now,
            )

    def test_driver_arrived_can_move_to_in_progress(self):
        db = RecordingSession()

        trip = self.build_trip(
            status="driver_arrived",
        )

        transition_trip(
            db=db,
            trip=trip,
            target_status=(
                "in_progress"
            ),
            actor_user_id=(
                self.actor_user_id
            ),
            event_type=(
                "trip_started"
            ),
            now=self.now,
        )

        self.assertEqual(
            trip.status,
            "in_progress",
        )

        self.assertEqual(
            trip.started_at,
            self.now,
        )

    def test_in_progress_can_complete(self):
        db = RecordingSession()

        trip = self.build_trip(
            status="in_progress",
        )

        transition_trip(
            db=db,
            trip=trip,
            target_status=(
                "completed"
            ),
            actor_user_id=(
                self.actor_user_id
            ),
            event_type=(
                "trip_completed"
            ),
            now=self.now,
        )

        self.assertEqual(
            trip.status,
            "completed",
        )

        self.assertEqual(
            trip.completed_at,
            self.now,
        )


if __name__ == "__main__":
    unittest.main()