from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.trip_location_verification import (
    TripLocationVerificationState,
)
from app.services.pickup_location import (
    ABUJA_PICKUP_LOCATION_POLICY,
    LocationSampleConflictError,
    LocationSampleRejectedError,
    LocationSampleSequenceError,
    has_verified_pickup_arrival,
    has_verified_pickup_progress,
    process_pickup_location_observation,
    redact_transient_location_state,
)


class PickupLocationVerificationTests(
    unittest.TestCase
):
    def setUp(self):
        self.now = datetime(
            2026,
            9,
            17,
            1,
            0,
            tzinfo=UTC,
        )

        self.trip_id = uuid4()
        self.assignment_id = uuid4()

        self.pickup_latitude = Decimal(
            "9.0765000"
        )

        self.pickup_longitude = Decimal(
            "7.3986000"
        )

    def build_state(
        self,
    ) -> TripLocationVerificationState:
        return TripLocationVerificationState(
            trip_id=self.trip_id,
            assignment_id=(
                self.assignment_id
            ),
            last_sample_id=None,
            last_latitude=None,
            last_longitude=None,
            last_horizontal_accuracy_m=None,
            last_distance_to_pickup_m=None,
            last_sample_captured_at=None,
            last_sample_received_at=None,
            progress_anchor_distance_to_pickup_m=None,
            progress_anchor_horizontal_accuracy_m=None,
            progress_anchor_captured_at=None,
            arrival_candidate_count=0,
            last_arrival_candidate_at=None,
            progress_verified_at=None,
            arrival_verified_at=None,
            created_at=self.now,
            updated_at=self.now,
        )

    def process(
        self,
        *,
        state,
        sample_id=None,
        latitude=None,
        longitude=None,
        accuracy="10.00",
        captured_at=None,
        assignment_id=None,
        is_mocked=None,
        speed=None,
        now=None,
    ):
        return (
            process_pickup_location_observation(
                state=state,
                assignment_id=(
                    assignment_id
                    or self.assignment_id
                ),
                pickup_latitude=(
                    self.pickup_latitude
                ),
                pickup_longitude=(
                    self.pickup_longitude
                ),
                sample_id=(
                    sample_id
                    or uuid4()
                ),
                latitude=(
                    latitude
                    or self.pickup_latitude
                ),
                longitude=(
                    longitude
                    or self.pickup_longitude
                ),
                horizontal_accuracy_m=(
                    Decimal(accuracy)
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
                now=(
                    now
                    or self.now
                ),
            )
        )

    def test_approved_policy_values(self):
        policy = (
            ABUJA_PICKUP_LOCATION_POLICY
        )

        self.assertEqual(
            policy.arrival_radius_m,
            100.0,
        )

        self.assertEqual(
            policy.max_horizontal_accuracy_m,
            50.0,
        )

        self.assertEqual(
            policy.max_sample_age_seconds,
            15,
        )

        self.assertEqual(
            policy.min_arrival_sample_separation_seconds,
            3,
        )

        self.assertEqual(
            policy.max_arrival_sample_separation_seconds,
            10,
        )

    def test_one_good_sample_is_only_candidate(self):
        state = self.build_state()

        result = self.process(
            state=state,
        )

        self.assertFalse(
            result.arrival_verified
        )

        self.assertEqual(
            result.arrival_candidate_count,
            1,
        )

    def test_two_good_samples_verify_arrival(self):
        state = self.build_state()

        self.process(
            state=state,
            captured_at=self.now,
        )

        result = self.process(
            state=state,
            captured_at=(
                self.now
                + timedelta(seconds=5)
            ),
            now=(
                self.now
                + timedelta(seconds=5)
            ),
        )

        self.assertTrue(
            result.arrival_verified
        )

        self.assertTrue(
            result.arrival_newly_verified
        )

        self.assertTrue(
            result.progress_verified
        )

    def test_samples_too_close_do_not_confirm_arrival(self):
        state = self.build_state()

        self.process(
            state=state,
        )

        result = self.process(
            state=state,
            captured_at=(
                self.now
                + timedelta(seconds=1)
            ),
            now=(
                self.now
                + timedelta(seconds=1)
            ),
        )

        self.assertFalse(
            result.arrival_verified
        )

        self.assertEqual(
            result.arrival_candidate_count,
            1,
        )

    def test_poor_accuracy_is_rejected(self):
        state = self.build_state()

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.process(
                state=state,
                accuracy="60.00",
            )

    def test_stale_sample_is_rejected(self):
        state = self.build_state()

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.process(
                state=state,
                captured_at=(
                    self.now
                    - timedelta(seconds=16)
                ),
            )

    def test_future_sample_is_rejected(self):
        state = self.build_state()

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.process(
                state=state,
                captured_at=(
                    self.now
                    + timedelta(seconds=6)
                ),
            )

    def test_mock_location_signal_is_rejected(self):
        state = self.build_state()

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.process(
                state=state,
                is_mocked=True,
            )

    def test_out_of_order_sample_is_rejected(self):
        state = self.build_state()

        self.process(
            state=state,
        )

        with self.assertRaises(
            LocationSampleSequenceError
        ):
            self.process(
                state=state,
                captured_at=(
                    self.now
                    - timedelta(seconds=1)
                ),
            )

    def test_implausible_jump_is_rejected(self):
        state = self.build_state()

        self.process(
            state=state,
            latitude=Decimal(
                "9.0965000"
            ),
            longitude=(
                self.pickup_longitude
            ),
        )

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.process(
                state=state,
                latitude=(
                    self.pickup_latitude
                ),
                longitude=(
                    self.pickup_longitude
                ),
                captured_at=(
                    self.now
                    + timedelta(seconds=1)
                ),
                now=(
                    self.now
                    + timedelta(seconds=1)
                ),
            )

    def test_meaningful_movement_verifies_progress(self):
        state = self.build_state()

        first_time = self.now

        self.process(
            state=state,
            latitude=Decimal(
                "9.0965000"
            ),
            longitude=(
                self.pickup_longitude
            ),
            captured_at=first_time,
        )

        second_time = (
            first_time
            + timedelta(seconds=10)
        )

        result = self.process(
            state=state,
            latitude=Decimal(
                "9.0945000"
            ),
            longitude=(
                self.pickup_longitude
            ),
            captured_at=second_time,
            now=second_time,
        )

        self.assertTrue(
            result.progress_verified
        )

        self.assertTrue(
            result.progress_newly_verified
        )

    def test_exact_replay_is_idempotent(self):
        state = self.build_state()

        sample_id = uuid4()

        self.process(
            state=state,
            sample_id=sample_id,
        )

        result = self.process(
            state=state,
            sample_id=sample_id,
            now=(
                self.now
                + timedelta(seconds=30)
            ),
        )

        self.assertTrue(
            result.replayed
        )

        self.assertEqual(
            result.arrival_candidate_count,
            1,
        )

    def test_same_sample_id_with_different_data_conflicts(self):
        state = self.build_state()

        sample_id = uuid4()

        self.process(
            state=state,
            sample_id=sample_id,
        )

        with self.assertRaises(
            LocationSampleConflictError
        ):
            self.process(
                state=state,
                sample_id=sample_id,
                latitude=Decimal(
                    "9.0764000"
                ),
            )

    def test_new_assignment_resets_old_evidence(self):
        state = self.build_state()

        state.progress_verified_at = (
            self.now
        )

        state.arrival_verified_at = (
            self.now
        )

        new_assignment_id = uuid4()

        result = self.process(
            state=state,
            assignment_id=(
                new_assignment_id
            ),
        )

        self.assertEqual(
            state.assignment_id,
            new_assignment_id,
        )

        self.assertFalse(
            result.arrival_verified
        )

        self.assertFalse(
            result.progress_verified
        )

    def test_helpers_are_assignment_scoped(self):
        state = self.build_state()

        state.progress_verified_at = (
            self.now
        )

        state.arrival_verified_at = (
            self.now
        )

        self.assertTrue(
            has_verified_pickup_progress(
                state=state,
                assignment_id=(
                    self.assignment_id
                ),
            )
        )

        self.assertTrue(
            has_verified_pickup_arrival(
                state=state,
                assignment_id=(
                    self.assignment_id
                ),
            )
        )

        other_assignment = uuid4()

        self.assertFalse(
            has_verified_pickup_progress(
                state=state,
                assignment_id=(
                    other_assignment
                ),
            )
        )

    def test_redaction_removes_transient_coordinates(self):
        state = self.build_state()

        self.process(
            state=state,
        )

        redact_transient_location_state(
            state=state,
            now=self.now,
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


if __name__ == "__main__":
    unittest.main()