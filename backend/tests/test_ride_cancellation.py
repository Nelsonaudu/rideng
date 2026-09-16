from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.driver_assignment import DriverAssignment
from app.models.ride_offer import RideOffer
from app.models.ride_request import RideRequest
from app.models.trip import Trip
from app.models.trip_start_verification import TripStartVerification
from app.services.ride_cancellation import (
    ABUJA_CANCELLATION_POLICY,
    DriverCancellationStateError,
    RiderCancellationStateError,
    RiderNoShowError,
    cancel_driver_assignment_for_rematch,
    cancel_ride_by_rider,
    mark_rider_no_show,
    rider_cancellation_fee_eligible,
)


class RideCancellationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(
            2026,
            9,
            17,
            0,
            30,
            tzinfo=UTC,
        )

        self.ride_request_id = uuid4()
        self.rider_id = uuid4()
        self.driver_id = uuid4()
        self.vehicle_id = uuid4()
        self.assignment_id = uuid4()
        self.offer_id = uuid4()
        self.trip_id = uuid4()

        self.ride_request = RideRequest(
            id=self.ride_request_id,
            rider_id=self.rider_id,
            ride_mode="quick_ride",
            status="matched",
            payment_method="cash",
            pickup_address="Wuse 2",
            pickup_latitude=Decimal("9.0765000"),
            pickup_longitude=Decimal("7.3986000"),
            destination_address="Gwarinpa",
            destination_latitude=Decimal("9.1099000"),
            destination_longitude=Decimal("7.4042000"),
            recommended_fare=Decimal("5000.00"),
            minimum_offer_fare=Decimal("4000.00"),
            quick_ride_fare=Decimal("5750.00"),
            maximum_counteroffer_fare=Decimal("6750.00"),
            matched_fare=Decimal("5750.00"),
        )

        self.assignment = DriverAssignment(
            id=self.assignment_id,
            ride_request_id=self.ride_request_id,
            driver_id=self.driver_id,
            vehicle_id=self.vehicle_id,
            ride_offer_id=self.offer_id,
            status="active",
            assigned_at=(
                self.now
                - timedelta(minutes=5)
            ),
        )

        self.offer = RideOffer(
            id=self.offer_id,
            ride_request_id=self.ride_request_id,
            driver_id=self.driver_id,
            vehicle_id=self.vehicle_id,
            status="selected",
            offered_at=(
                self.now
                - timedelta(minutes=6)
            ),
            expires_at=(
                self.now
                - timedelta(minutes=5)
            ),
            responded_at=(
                self.now
                - timedelta(minutes=5)
            ),
        )

        self.trip = Trip(
            id=self.trip_id,
            ride_request_id=self.ride_request_id,
            active_assignment_id=self.assignment_id,
            rider_id=self.rider_id,
            status="driver_arriving",
            agreed_fare=Decimal("5750.00"),
            payment_method="cash",
            matched_at=(
                self.now
                - timedelta(minutes=5)
            ),
            driver_arriving_at=(
                self.now
                - timedelta(minutes=4)
            ),
        )

        self.verification = TripStartVerification(
            id=uuid4(),
            trip_id=self.trip_id,
            assignment_id=self.assignment_id,
            pin_hash="hashed-pin",
            attempt_count=0,
            locked_until=None,
            expires_at=(
                self.now
                + timedelta(hours=1)
            ),
            verified_at=None,
            invalidated_at=None,
            created_at=self.now,
        )

    def test_policy_uses_approved_grace_periods(self):
        self.assertEqual(
            ABUJA_CANCELLATION_POLICY
            .rider_free_cancel_seconds,
            120,
        )

        self.assertEqual(
            ABUJA_CANCELLATION_POLICY
            .rider_no_show_wait_seconds,
            300,
        )

    def test_rider_cancel_inside_grace_is_free(self):
        eligible = (
            rider_cancellation_fee_eligible(
                assigned_at=self.now,
                cancelled_at=(
                    self.now
                    + timedelta(seconds=119)
                ),
                driver_progress_verified=True,
            )
        )

        self.assertFalse(
            eligible
        )

    def test_rider_cancel_after_grace_needs_progress(self):
        eligible = (
            rider_cancellation_fee_eligible(
                assigned_at=self.now,
                cancelled_at=(
                    self.now
                    + timedelta(seconds=121)
                ),
                driver_progress_verified=False,
            )
        )

        self.assertFalse(
            eligible
        )

    def test_rider_cancel_after_grace_with_progress_can_charge(self):
        eligible = (
            rider_cancellation_fee_eligible(
                assigned_at=self.now,
                cancelled_at=(
                    self.now
                    + timedelta(seconds=121)
                ),
                driver_progress_verified=True,
            )
        )

        self.assertTrue(
            eligible
        )

    def test_driver_cancel_returns_request_to_searching(self):
        cancel_driver_assignment_for_rematch(
            ride_request=self.ride_request,
            trip=self.trip,
            assignment=self.assignment,
            offer=self.offer,
            verification=self.verification,
            reason="vehicle_issue",
            now=self.now,
        )

        self.assertEqual(
            self.ride_request.status,
            "searching",
        )

        self.assertIsNone(
            self.ride_request.matched_fare
        )

        self.assertEqual(
            self.assignment.status,
            "cancelled",
        )

        self.assertEqual(
            self.assignment.cancellation_reason,
            "vehicle_issue",
        )

        self.assertIsNone(
            self.trip.active_assignment_id
        )

        self.assertEqual(
            self.trip.status,
            "matched",
        )

        self.assertIsNone(
            self.trip.driver_arriving_at
        )

        self.assertEqual(
            self.offer.status,
            "closed",
        )

        self.assertEqual(
            self.verification.invalidated_at,
            self.now,
        )

    def test_driver_cannot_normally_cancel_in_progress_trip(self):
        self.trip.status = "in_progress"

        with self.assertRaises(
            DriverCancellationStateError
        ):
            cancel_driver_assignment_for_rematch(
                ride_request=self.ride_request,
                trip=self.trip,
                assignment=self.assignment,
                offer=self.offer,
                verification=self.verification,
                reason="changed_mind",
                now=self.now,
            )

    def test_rider_cancellation_terminates_matched_trip(self):
        result = cancel_ride_by_rider(
            ride_request=self.ride_request,
            trip=self.trip,
            assignment=self.assignment,
            offer=self.offer,
            verification=self.verification,
            driver_progress_verified=True,
            now=self.now,
        )

        self.assertEqual(
            self.ride_request.status,
            "rider_cancelled",
        )

        self.assertEqual(
            self.trip.status,
            "rider_cancelled",
        )

        self.assertIsNone(
            self.trip.active_assignment_id
        )

        self.assertEqual(
            self.assignment.status,
            "cancelled",
        )

        self.assertEqual(
            self.offer.status,
            "closed",
        )

        self.assertTrue(
            result.cancellation_fee_eligible
        )

    def test_rider_cannot_cancel_started_trip_normally(self):
        self.trip.status = "in_progress"

        with self.assertRaises(
            RiderCancellationStateError
        ):
            cancel_ride_by_rider(
                ride_request=self.ride_request,
                trip=self.trip,
                assignment=self.assignment,
                offer=self.offer,
                verification=self.verification,
                driver_progress_verified=True,
                now=self.now,
            )

    def test_no_show_requires_five_minutes_wait(self):
        self.trip.status = "driver_arrived"
        self.trip.arrived_at = (
            self.now
            - timedelta(
                seconds=299
            )
        )

        with self.assertRaises(
            RiderNoShowError
        ):
            mark_rider_no_show(
                ride_request=self.ride_request,
                trip=self.trip,
                assignment=self.assignment,
                verification=self.verification,
                arrival_verified=True,
                now=self.now,
            )

    def test_no_show_requires_verified_arrival(self):
        self.trip.status = "driver_arrived"
        self.trip.arrived_at = (
            self.now
            - timedelta(
                seconds=301
            )
        )

        with self.assertRaises(
            RiderNoShowError
        ):
            mark_rider_no_show(
                ride_request=self.ride_request,
                trip=self.trip,
                assignment=self.assignment,
                verification=self.verification,
                arrival_verified=False,
                now=self.now,
            )

    def test_valid_no_show_closes_assignment(self):
        self.trip.status = "driver_arrived"
        self.trip.arrived_at = (
            self.now
            - timedelta(
                seconds=301
            )
        )

        result = mark_rider_no_show(
            ride_request=self.ride_request,
            trip=self.trip,
            assignment=self.assignment,
            verification=self.verification,
            arrival_verified=True,
            now=self.now,
        )

        self.assertEqual(
            self.trip.status,
            "rider_no_show",
        )

        self.assertIsNone(
            self.trip.active_assignment_id
        )

        self.assertEqual(
            self.assignment.status,
            "completed",
        )

        self.assertTrue(
            result.driver_compensation_eligible
        )

        self.assertEqual(
            self.verification.invalidated_at,
            self.now,
        )


if __name__ == "__main__":
    unittest.main()