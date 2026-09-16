from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.ride_offer import RideOffer
from app.models.ride_request import RideRequest
from app.services.driver_readiness import (
    DriverReadinessSnapshot,
)
from app.services.ride_assignment import (
    RideAssignmentEligibilityError,
    RideAssignmentOfferError,
    ensure_driver_vehicle_eligible,
    matched_fare_for_offer,
    selection_deadline_for_offer,
)


class RideAssignmentRuleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(
            2026,
            9,
            16,
            22,
            0,
            tzinfo=UTC,
        )

        self.driver_id = uuid4()
        self.vehicle_id = uuid4()

        self.quick_request = RideRequest(
            id=uuid4(),
            rider_id=uuid4(),
            ride_mode="quick_ride",
            status="searching",
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
        )

        self.negotiated_request = RideRequest(
            id=uuid4(),
            rider_id=uuid4(),
            ride_mode="negotiate",
            status="searching",
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
            rider_offer_fare=Decimal("4500.00"),
        )

    def test_quick_ride_uses_locked_quick_fare(self):
        offer = RideOffer(
            id=uuid4(),
            ride_request_id=self.quick_request.id,
            driver_id=self.driver_id,
            vehicle_id=self.vehicle_id,
            status="accepted",
            offered_at=self.now,
            expires_at=(
                self.now
                + timedelta(seconds=10)
            ),
            responded_at=self.now,
        )

        fare = matched_fare_for_offer(
            ride_request=self.quick_request,
            offer=offer,
        )

        self.assertEqual(
            fare,
            Decimal("5750.00"),
        )

    def test_negotiated_accept_uses_rider_offer(self):
        offer = RideOffer(
            id=uuid4(),
            ride_request_id=self.negotiated_request.id,
            driver_id=self.driver_id,
            vehicle_id=self.vehicle_id,
            rider_offer_fare=Decimal("4500.00"),
            status="accepted",
            offered_at=self.now,
            expires_at=(
                self.now
                + timedelta(seconds=25)
            ),
            responded_at=self.now,
        )

        fare = matched_fare_for_offer(
            ride_request=self.negotiated_request,
            offer=offer,
        )

        self.assertEqual(
            fare,
            Decimal("4500.00"),
        )

    def test_negotiated_counter_uses_counteroffer(self):
        offer = RideOffer(
            id=uuid4(),
            ride_request_id=self.negotiated_request.id,
            driver_id=self.driver_id,
            vehicle_id=self.vehicle_id,
            rider_offer_fare=Decimal("4500.00"),
            driver_counteroffer_fare=Decimal("5200.00"),
            status="countered",
            offered_at=self.now,
            expires_at=(
                self.now
                + timedelta(seconds=25)
            ),
            responded_at=self.now,
        )

        fare = matched_fare_for_offer(
            ride_request=self.negotiated_request,
            offer=offer,
        )

        self.assertEqual(
            fare,
            Decimal("5200.00"),
        )

    def test_invalid_negotiated_offer_state_rejected(self):
        offer = RideOffer(
            id=uuid4(),
            ride_request_id=self.negotiated_request.id,
            driver_id=self.driver_id,
            vehicle_id=self.vehicle_id,
            status="open",
            offered_at=self.now,
            expires_at=(
                self.now
                + timedelta(seconds=25)
            ),
        )

        with self.assertRaises(
            RideAssignmentOfferError
        ):
            matched_fare_for_offer(
                ride_request=self.negotiated_request,
                offer=offer,
            )

    def test_selection_deadline_is_30_seconds(self):
        offer = RideOffer(
            id=uuid4(),
            ride_request_id=self.negotiated_request.id,
            driver_id=self.driver_id,
            vehicle_id=self.vehicle_id,
            status="accepted",
            offered_at=self.now,
            expires_at=(
                self.now
                + timedelta(seconds=25)
            ),
            responded_at=self.now,
        )

        self.assertEqual(
            selection_deadline_for_offer(
                offer=offer,
            ),
            self.now + timedelta(seconds=30),
        )

    def test_eligible_driver_and_vehicle_pass(self):
        readiness = DriverReadinessSnapshot(
            driver_id=self.driver_id,
            user_active=True,
            driver_compliance_approved=True,
            driver_documents_valid=True,
            eligible_vehicle_ids=[
                self.vehicle_id,
            ],
            online_eligible=True,
            missing_or_invalid_driver_requirements=[],
            blockers=[],
        )

        ensure_driver_vehicle_eligible(
            readiness=readiness,
            driver_is_online=True,
            vehicle_id=self.vehicle_id,
        )

    def test_offline_driver_is_rejected(self):
        readiness = DriverReadinessSnapshot(
            driver_id=self.driver_id,
            user_active=True,
            driver_compliance_approved=True,
            driver_documents_valid=True,
            eligible_vehicle_ids=[
                self.vehicle_id,
            ],
            online_eligible=True,
            missing_or_invalid_driver_requirements=[],
            blockers=[],
        )

        with self.assertRaises(
            RideAssignmentEligibilityError
        ):
            ensure_driver_vehicle_eligible(
                readiness=readiness,
                driver_is_online=False,
                vehicle_id=self.vehicle_id,
            )

    def test_ineligible_vehicle_is_rejected(self):
        readiness = DriverReadinessSnapshot(
            driver_id=self.driver_id,
            user_active=True,
            driver_compliance_approved=True,
            driver_documents_valid=True,
            eligible_vehicle_ids=[],
            online_eligible=False,
            missing_or_invalid_driver_requirements=[],
            blockers=[
                "no_ride_eligible_vehicle",
            ],
        )

        with self.assertRaises(
            RideAssignmentEligibilityError
        ):
            ensure_driver_vehicle_eligible(
                readiness=readiness,
                driver_is_online=True,
                vehicle_id=self.vehicle_id,
            )


if __name__ == "__main__":
    unittest.main()