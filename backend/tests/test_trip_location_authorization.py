from datetime import UTC, datetime
import unittest
from unittest.mock import Mock
from uuid import uuid4

from app.api.routes.trips import (
    _pickup_arrival_is_verified,
)
from app.models.trip_location_verification import (
    TripLocationVerificationState,
)


class TripLocationAuthorizationTests(
    unittest.TestCase
):
    def setUp(self):
        self.trip_id = uuid4()
        self.old_assignment_id = uuid4()
        self.current_assignment_id = uuid4()

        self.now = datetime(
            2026,
            9,
            17,
            18,
            0,
            tzinfo=UTC,
        )

    def test_old_assignment_arrival_does_not_authorize_current_driver(
        self,
    ):
        state = (
            TripLocationVerificationState(
                trip_id=self.trip_id,
                assignment_id=(
                    self.old_assignment_id
                ),
                arrival_verified_at=(
                    self.now
                ),
            )
        )

        db = Mock()
        db.scalar.return_value = state

        verified = (
            _pickup_arrival_is_verified(
                db=db,
                trip_id=self.trip_id,
                assignment_id=(
                    self.current_assignment_id
                ),
            )
        )

        self.assertFalse(
            verified
        )

    def test_current_assignment_arrival_is_authorized(
        self,
    ):
        state = (
            TripLocationVerificationState(
                trip_id=self.trip_id,
                assignment_id=(
                    self.current_assignment_id
                ),
                arrival_verified_at=(
                    self.now
                ),
            )
        )

        db = Mock()
        db.scalar.return_value = state

        verified = (
            _pickup_arrival_is_verified(
                db=db,
                trip_id=self.trip_id,
                assignment_id=(
                    self.current_assignment_id
                ),
            )
        )

        self.assertTrue(
            verified
        )


if __name__ == "__main__":
    unittest.main()