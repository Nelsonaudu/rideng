from datetime import UTC, datetime
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.trip_location_verification import (
    TripLocationVerificationState,
)
from app.services.pickup_location import (
    redact_location_for_assignment,
)


class PickupLocationLifecycleTests(
    unittest.TestCase
):
    def setUp(self):
        self.trip_id = uuid4()
        self.assignment_id = uuid4()

        self.now = datetime(
            2026,
            9,
            17,
            18,
            30,
            tzinfo=UTC,
        )

    def build_state(
        self,
        *,
        assignment_id=None,
    ):
        return TripLocationVerificationState(
            trip_id=self.trip_id,
            assignment_id=(
                assignment_id
                or self.assignment_id
            ),
            last_sample_id=uuid4(),
            last_latitude=Decimal(
                "9.0765000"
            ),
            last_longitude=Decimal(
                "7.3986000"
            ),
            last_horizontal_accuracy_m=(
                Decimal("12.00")
            ),
            last_distance_to_pickup_m=(
                Decimal("45.00")
            ),
            last_sample_captured_at=(
                self.now
            ),
            last_sample_received_at=(
                self.now
            ),
            progress_anchor_distance_to_pickup_m=(
                Decimal("300.00")
            ),
            progress_anchor_horizontal_accuracy_m=(
                Decimal("15.00")
            ),
            progress_anchor_captured_at=(
                self.now
            ),
            arrival_candidate_count=2,
            last_arrival_candidate_at=(
                self.now
            ),
            progress_verified_at=(
                self.now
            ),
            arrival_verified_at=(
                self.now
            ),
        )

    def test_matching_assignment_is_redacted(
        self,
    ):
        state = self.build_state()

        redacted = (
            redact_location_for_assignment(
                state=state,
                assignment_id=(
                    self.assignment_id
                ),
                now=self.now,
            )
        )

        self.assertTrue(
            redacted
        )

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
            state.last_sample_id
        )

        self.assertEqual(
            state.progress_verified_at,
            self.now,
        )

        self.assertEqual(
            state.arrival_verified_at,
            self.now,
        )

    def test_old_assignment_cannot_redact_new_assignment(
        self,
    ):
        new_assignment_id = uuid4()

        state = self.build_state(
            assignment_id=(
                new_assignment_id
            )
        )

        redacted = (
            redact_location_for_assignment(
                state=state,
                assignment_id=(
                    self.assignment_id
                ),
                now=self.now,
            )
        )

        self.assertFalse(
            redacted
        )

        self.assertEqual(
            state.last_latitude,
            Decimal("9.0765000"),
        )

        self.assertEqual(
            state.assignment_id,
            new_assignment_id,
        )

    def test_missing_state_is_safe_noop(
        self,
    ):
        redacted = (
            redact_location_for_assignment(
                state=None,
                assignment_id=(
                    self.assignment_id
                ),
                now=self.now,
            )
        )

        self.assertFalse(
            redacted
        )


if __name__ == "__main__":
    unittest.main()