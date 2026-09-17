from datetime import UTC, datetime
import unittest
from unittest.mock import Mock
from uuid import uuid4

from app.api.routes.ride_cancellation import (
    _pickup_arrival_is_verified,
    _pickup_progress_is_verified,
)
from app.models.trip_location_verification import (
    TripLocationVerificationState,
)


class CancellationLocationAuthorizationTests(
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
            15,
            tzinfo=UTC,
        )

    def build_state(
        self,
        *,
        assignment_id,
        progress=False,
        arrival=False,
    ):
        return TripLocationVerificationState(
            trip_id=self.trip_id,
            assignment_id=assignment_id,
            progress_verified_at=(
                self.now
                if progress
                else None
            ),
            arrival_verified_at=(
                self.now
                if arrival
                else None
            ),
        )

    def test_old_assignment_progress_does_not_authorize_rider_fee(
        self,
    ):
        state = self.build_state(
            assignment_id=(
                self.old_assignment_id
            ),
            progress=True,
        )

        db = Mock()
        db.scalar.return_value = state

        verified = (
            _pickup_progress_is_verified(
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

    def test_current_assignment_progress_is_authorized(
        self,
    ):
        state = self.build_state(
            assignment_id=(
                self.current_assignment_id
            ),
            progress=True,
        )

        db = Mock()
        db.scalar.return_value = state

        verified = (
            _pickup_progress_is_verified(
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

    def test_old_assignment_arrival_does_not_authorize_no_show(
        self,
    ):
        state = self.build_state(
            assignment_id=(
                self.old_assignment_id
            ),
            arrival=True,
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

    def test_current_assignment_arrival_authorizes_no_show(
        self,
    ):
        state = self.build_state(
            assignment_id=(
                self.current_assignment_id
            ),
            arrival=True,
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