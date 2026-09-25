from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from uuid import uuid4


try:
    from app.services.location_verification import (
        ArrivalLocationPolicy,
        LocationSample,
        LocationSampleConflictError,
        LocationSampleRejectedError,
        LocationSampleSequenceError,
        advance_arrival_confirmation,
        validate_location_sample,
    )
except ImportError:
    ArrivalLocationPolicy = None
    LocationSample = None
    LocationSampleConflictError = None
    LocationSampleRejectedError = None
    LocationSampleSequenceError = None
    advance_arrival_confirmation = None
    validate_location_sample = None


class LocationVerificationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            ArrivalLocationPolicy,
            "ArrivalLocationPolicy must exist.",
        )

        self.assertIsNotNone(
            LocationSample,
            "LocationSample must exist.",
        )

        self.assertIsNotNone(
            validate_location_sample,
            "validate_location_sample must exist.",
        )

        self.assertIsNotNone(
            advance_arrival_confirmation,
            "advance_arrival_confirmation must exist.",
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

        self.target_latitude = Decimal(
            "9.0765000"
        )

        self.target_longitude = Decimal(
            "7.3986000"
        )

        self.policy = ArrivalLocationPolicy(
            arrival_radius_m=100.0,
            max_horizontal_accuracy_m=50.0,
            max_sample_age_seconds=15,
            max_future_skew_seconds=5,
            min_confirmation_separation_seconds=3,
            max_confirmation_separation_seconds=10,
            max_plausible_speed_mps=55.0,
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
                or self.target_latitude
            ),
            longitude=(
                longitude
                or self.target_longitude
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
        )

    def validate(
        self,
        *,
        sample,
        previous_sample=None,
        now=None,
    ):
        return validate_location_sample(
            sample=sample,
            target_latitude=(
                self.target_latitude
            ),
            target_longitude=(
                self.target_longitude
            ),
            previous_sample=(
                previous_sample
            ),
            now=(
                now
                or self.now
            ),
            policy=self.policy,
        )

    def test_valid_sample_returns_distance(self):
        result = self.validate(
            sample=self.sample(),
        )

        self.assertFalse(
            result.replayed
        )

        self.assertGreaterEqual(
            result.distance_to_target_m,
            0.0,
        )

    def test_exact_replay_is_idempotent(self):
        sample_id = uuid4()

        previous = self.sample(
            sample_id=sample_id,
        )

        current = self.sample(
            sample_id=sample_id,
        )

        result = self.validate(
            sample=current,
            previous_sample=previous,
            now=(
                self.now
                + timedelta(seconds=30)
            ),
        )

        self.assertTrue(
            result.replayed
        )

    def test_same_sample_id_with_different_data_conflicts(self):
        sample_id = uuid4()

        previous = self.sample(
            sample_id=sample_id,
        )

        current = self.sample(
            sample_id=sample_id,
            latitude=Decimal(
                "9.0764000"
            ),
        )

        with self.assertRaises(
            LocationSampleConflictError
        ):
            self.validate(
                sample=current,
                previous_sample=previous,
            )

    def test_poor_accuracy_is_rejected(self):
        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.validate(
                sample=self.sample(
                    accuracy="60.00"
                ),
            )

    def test_zero_accuracy_is_rejected(self):
        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.validate(
                sample=self.sample(
                    accuracy="0.00"
                ),
            )

    def test_stale_sample_is_rejected(self):
        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.validate(
                sample=self.sample(
                    captured_at=(
                        self.now
                        - timedelta(
                            seconds=16
                        )
                    ),
                ),
            )

    def test_future_sample_is_rejected(self):
        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.validate(
                sample=self.sample(
                    captured_at=(
                        self.now
                        + timedelta(
                            seconds=6
                        )
                    ),
                ),
            )

    def test_naive_timestamp_is_rejected(self):
        naive = datetime(
            2026,
            9,
            25,
            12,
            0,
            0,
        )

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.validate(
                sample=self.sample(
                    captured_at=naive,
                ),
            )

    def test_mock_location_is_rejected(self):
        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.validate(
                sample=self.sample(
                    is_mocked=True,
                ),
            )

    def test_reported_speed_is_rejected(self):
        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.validate(
                sample=self.sample(
                    speed="56.00",
                ),
            )

    def test_out_of_order_sample_is_rejected(self):
        previous = self.sample(
            captured_at=self.now,
        )

        current = self.sample(
            captured_at=(
                self.now
                - timedelta(seconds=1)
            ),
        )

        with self.assertRaises(
            LocationSampleSequenceError
        ):
            self.validate(
                sample=current,
                previous_sample=previous,
            )

    def test_implausible_movement_is_rejected(self):
        previous = self.sample(
            latitude=Decimal(
                "9.0965000"
            ),
            captured_at=self.now,
        )

        current = self.sample(
            latitude=(
                self.target_latitude
            ),
            captured_at=(
                self.now
                + timedelta(seconds=1)
            ),
        )

        with self.assertRaises(
            LocationSampleRejectedError
        ):
            self.validate(
                sample=current,
                previous_sample=previous,
                now=(
                    self.now
                    + timedelta(seconds=1)
                ),
            )

    def test_uncertainty_aware_arrival_candidate(self):
        result = self.validate(
            sample=self.sample(
                accuracy="10.00",
            ),
        )

        confirmation = (
            advance_arrival_confirmation(
                candidate_count=0,
                last_candidate_at=None,
                already_verified=False,
                distance_to_target_m=(
                    result.distance_to_target_m
                ),
                horizontal_accuracy_m=(
                    Decimal("10.00")
                ),
                captured_at=self.now,
                policy=self.policy,
            )
        )

        self.assertEqual(
            confirmation.candidate_count,
            1,
        )

        self.assertFalse(
            confirmation.arrival_verified
        )

    def test_two_good_samples_verify_arrival(self):
        first = advance_arrival_confirmation(
            candidate_count=0,
            last_candidate_at=None,
            already_verified=False,
            distance_to_target_m=0.0,
            horizontal_accuracy_m=(
                Decimal("10.00")
            ),
            captured_at=self.now,
            policy=self.policy,
        )

        second = advance_arrival_confirmation(
            candidate_count=(
                first.candidate_count
            ),
            last_candidate_at=(
                first.last_candidate_at
            ),
            already_verified=False,
            distance_to_target_m=0.0,
            horizontal_accuracy_m=(
                Decimal("10.00")
            ),
            captured_at=(
                self.now
                + timedelta(seconds=5)
            ),
            policy=self.policy,
        )

        self.assertEqual(
            second.candidate_count,
            2,
        )

        self.assertTrue(
            second.arrival_verified
        )

        self.assertTrue(
            second.arrival_newly_verified
        )

    def test_samples_too_close_do_not_confirm(self):
        first = advance_arrival_confirmation(
            candidate_count=0,
            last_candidate_at=None,
            already_verified=False,
            distance_to_target_m=0.0,
            horizontal_accuracy_m=(
                Decimal("10.00")
            ),
            captured_at=self.now,
            policy=self.policy,
        )

        second = advance_arrival_confirmation(
            candidate_count=(
                first.candidate_count
            ),
            last_candidate_at=(
                first.last_candidate_at
            ),
            already_verified=False,
            distance_to_target_m=0.0,
            horizontal_accuracy_m=(
                Decimal("10.00")
            ),
            captured_at=(
                self.now
                + timedelta(seconds=1)
            ),
            policy=self.policy,
        )

        self.assertEqual(
            second.candidate_count,
            1,
        )

        self.assertFalse(
            second.arrival_verified
        )

    def test_late_second_candidate_resets_sequence(self):
        first = advance_arrival_confirmation(
            candidate_count=0,
            last_candidate_at=None,
            already_verified=False,
            distance_to_target_m=0.0,
            horizontal_accuracy_m=(
                Decimal("10.00")
            ),
            captured_at=self.now,
            policy=self.policy,
        )

        second = advance_arrival_confirmation(
            candidate_count=(
                first.candidate_count
            ),
            last_candidate_at=(
                first.last_candidate_at
            ),
            already_verified=False,
            distance_to_target_m=0.0,
            horizontal_accuracy_m=(
                Decimal("10.00")
            ),
            captured_at=(
                self.now
                + timedelta(seconds=11)
            ),
            policy=self.policy,
        )

        self.assertEqual(
            second.candidate_count,
            1,
        )

        self.assertFalse(
            second.arrival_verified
        )

    def test_non_candidate_resets_arrival_sequence(self):
        result = advance_arrival_confirmation(
            candidate_count=1,
            last_candidate_at=self.now,
            already_verified=False,
            distance_to_target_m=95.0,
            horizontal_accuracy_m=(
                Decimal("10.00")
            ),
            captured_at=(
                self.now
                + timedelta(seconds=5)
            ),
            policy=self.policy,
        )

        self.assertEqual(
            result.candidate_count,
            0,
        )

        self.assertIsNone(
            result.last_candidate_at
        )

        self.assertFalse(
            result.arrival_verified
        )


if __name__ == "__main__":
    unittest.main()
