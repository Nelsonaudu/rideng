from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.driver_assignment import DriverAssignment
from app.models.trip import Trip
from app.models.trip_start_verification import (
    TripStartVerification,
)
from app.services.trip_verification import (
    ABUJA_TRIP_PIN_POLICY,
    TripPinAlreadyVerifiedError,
    TripPinExpiredError,
    TripPinInvalidatedError,
    TripPinLockedError,
    TripStartAuthorizationError,
    check_trip_start_pin,
    ensure_trip_start_authorized,
    generate_trip_pin,
    hash_trip_pin,
    invalidate_trip_start_verification,
    issue_trip_start_pin,
    trip_pin_matches,
)


TEST_SECRET = "rideng-test-trip-pin-secret"


class TripVerificationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(
            2026,
            9,
            17,
            0,
            0,
            tzinfo=UTC,
        )

        self.trip_id = uuid4()
        self.assignment_id = uuid4()
        self.ride_request_id = uuid4()
        self.driver_id = uuid4()
        self.vehicle_id = uuid4()
        self.rider_id = uuid4()

        self.assignment = DriverAssignment(
            id=self.assignment_id,
            ride_request_id=self.ride_request_id,
            driver_id=self.driver_id,
            vehicle_id=self.vehicle_id,
            status="active",
            assigned_at=self.now,
        )

        self.trip = Trip(
            id=self.trip_id,
            ride_request_id=self.ride_request_id,
            active_assignment_id=self.assignment_id,
            rider_id=self.rider_id,
            status="driver_arrived",
            agreed_fare=Decimal("5750.00"),
            payment_method="cash",
            matched_at=self.now,
            arrived_at=self.now,
        )

    def issue_pin(self):
        return issue_trip_start_pin(
            trip=self.trip,
            assignment=self.assignment,
            existing_verification=None,
            now=self.now,
            secret=TEST_SECRET,
        )

    def test_generated_pin_is_exactly_four_digits(self):
        for _ in range(100):
            pin = generate_trip_pin()

            self.assertEqual(
                len(pin),
                4,
            )

            self.assertTrue(
                pin.isdigit()
            )

    def test_raw_pin_is_not_stored(self):
        result = self.issue_pin()

        verification = (
            result.verification
        )

        self.assertNotEqual(
            verification.pin_hash,
            result.pin,
        )

        self.assertNotIn(
            result.pin,
            verification.pin_hash,
        )

    def test_hash_verifies_correct_pin(self):
        pin = "0042"

        digest = hash_trip_pin(
            pin=pin,
            assignment_id=(
                self.assignment_id
            ),
            secret=TEST_SECRET,
        )

        self.assertTrue(
            trip_pin_matches(
                pin=pin,
                pin_hash=digest,
                assignment_id=(
                    self.assignment_id
                ),
                secret=TEST_SECRET,
            )
        )

        self.assertFalse(
            trip_pin_matches(
                pin="0043",
                pin_hash=digest,
                assignment_id=(
                    self.assignment_id
                ),
                secret=TEST_SECRET,
            )
        )

    def test_correct_pin_verifies(self):
        issued = self.issue_pin()

        result = check_trip_start_pin(
            verification=(
                issued.verification
            ),
            submitted_pin=issued.pin,
            now=self.now,
            secret=TEST_SECRET,
        )

        self.assertTrue(
            result.verified
        )

        self.assertEqual(
            issued.verification.verified_at,
            self.now,
        )

    def test_wrong_pin_increments_attempt_count(self):
        issued = self.issue_pin()

        wrong_pin = (
            "9999"
            if issued.pin != "9999"
            else "9998"
        )

        result = check_trip_start_pin(
            verification=(
                issued.verification
            ),
            submitted_pin=wrong_pin,
            now=self.now,
            secret=TEST_SECRET,
        )

        self.assertFalse(
            result.verified
        )

        self.assertEqual(
            issued.verification.attempt_count,
            1,
        )

        self.assertEqual(
            result.attempts_remaining,
            2,
        )

    def test_third_wrong_pin_locks_verification(self):
        issued = self.issue_pin()

        wrong_pin = (
            "9999"
            if issued.pin != "9999"
            else "9998"
        )

        for second in range(3):
            result = check_trip_start_pin(
                verification=(
                    issued.verification
                ),
                submitted_pin=wrong_pin,
                now=(
                    self.now
                    + timedelta(
                        seconds=second
                    )
                ),
                secret=TEST_SECRET,
            )

        self.assertFalse(
            result.verified
        )

        self.assertEqual(
            issued.verification.attempt_count,
            3,
        )

        self.assertIsNotNone(
            issued.verification.locked_until
        )

        self.assertEqual(
            result.attempts_remaining,
            0,
        )

    def test_locked_pin_rejects_attempt(self):
        issued = self.issue_pin()

        issued.verification.attempt_count = 3

        issued.verification.locked_until = (
            self.now
            + timedelta(
                seconds=30
            )
        )

        with self.assertRaises(
            TripPinLockedError
        ):
            check_trip_start_pin(
                verification=(
                    issued.verification
                ),
                submitted_pin=issued.pin,
                now=self.now,
                secret=TEST_SECRET,
            )

    def test_lock_expiry_allows_new_attempt_cycle(self):
        issued = self.issue_pin()

        issued.verification.attempt_count = 3

        issued.verification.locked_until = (
            self.now
            - timedelta(
                seconds=1
            )
        )

        wrong_pin = (
            "9999"
            if issued.pin != "9999"
            else "9998"
        )

        result = check_trip_start_pin(
            verification=(
                issued.verification
            ),
            submitted_pin=wrong_pin,
            now=self.now,
            secret=TEST_SECRET,
        )

        self.assertFalse(
            result.verified
        )

        self.assertEqual(
            issued.verification.attempt_count,
            1,
        )

    def test_verified_pin_cannot_be_verified_again(self):
        issued = self.issue_pin()

        check_trip_start_pin(
            verification=(
                issued.verification
            ),
            submitted_pin=issued.pin,
            now=self.now,
            secret=TEST_SECRET,
        )

        with self.assertRaises(
            TripPinAlreadyVerifiedError
        ):
            check_trip_start_pin(
                verification=(
                    issued.verification
                ),
                submitted_pin=issued.pin,
                now=(
                    self.now
                    + timedelta(
                        seconds=1
                    )
                ),
                secret=TEST_SECRET,
            )

    def test_expired_pin_is_rejected(self):
        issued = self.issue_pin()

        issued.verification.expires_at = (
            self.now
            - timedelta(
                seconds=1
            )
        )

        with self.assertRaises(
            TripPinExpiredError
        ):
            check_trip_start_pin(
                verification=(
                    issued.verification
                ),
                submitted_pin=issued.pin,
                now=self.now,
                secret=TEST_SECRET,
            )

    def test_invalidated_pin_is_rejected(self):
        issued = self.issue_pin()

        invalidate_trip_start_verification(
            verification=(
                issued.verification
            ),
            now=self.now,
        )

        with self.assertRaises(
            TripPinInvalidatedError
        ):
            check_trip_start_pin(
                verification=(
                    issued.verification
                ),
                submitted_pin=issued.pin,
                now=self.now,
                secret=TEST_SECRET,
            )

    def test_trip_start_requires_verified_pin(self):
        issued = self.issue_pin()

        with self.assertRaises(
            TripStartAuthorizationError
        ):
            ensure_trip_start_authorized(
                trip=self.trip,
                assignment=self.assignment,
                verification=(
                    issued.verification
                ),
                now=self.now,
            )

    def test_verified_pin_authorizes_start(self):
        issued = self.issue_pin()

        check_trip_start_pin(
            verification=(
                issued.verification
            ),
            submitted_pin=issued.pin,
            now=self.now,
            secret=TEST_SECRET,
        )

        ensure_trip_start_authorized(
            trip=self.trip,
            assignment=self.assignment,
            verification=(
                issued.verification
            ),
            now=self.now,
        )

    def test_policy_requires_three_attempts(self):
        self.assertEqual(
            ABUJA_TRIP_PIN_POLICY.max_attempts,
            3,
        )


if __name__ == "__main__":
    unittest.main()