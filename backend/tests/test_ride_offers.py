from datetime import UTC, datetime, timedelta
from decimal import Decimal
import unittest
from uuid import uuid4

from app.models.ride_offer import RideOffer
from app.models.ride_request import RideRequest
from app.services.ride_offers import (
    RideOfferExpiredError,
    RideOfferFareError,
    RideOfferModeError,
    RideOfferStateError,
    accept_offer,
    counter_offer,
    decline_offer,
    expire_offer,
    offer_expiration_for_request,
)


class RideOfferRuleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(
            2026,
            9,
            16,
            20,
            0,
            tzinfo=UTC,
        )

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

    def build_offer(
        self,
        *,
        request: RideRequest,
        status: str = "open",
        expires_at: datetime | None = None,
    ) -> RideOffer:
        return RideOffer(
            id=uuid4(),
            ride_request_id=request.id,
            driver_id=uuid4(),
            vehicle_id=uuid4(),
            rider_offer_fare=(
                request.rider_offer_fare
            ),
            status=status,
            offered_at=self.now,
            expires_at=(
                expires_at
                or self.now
                + timedelta(seconds=25)
            ),
        )

    def test_quick_ride_offer_expires_after_10_seconds(self):
        expires_at = offer_expiration_for_request(
            ride_mode="quick_ride",
            offered_at=self.now,
        )

        self.assertEqual(
            expires_at,
            self.now + timedelta(seconds=10),
        )

    def test_negotiation_offer_expires_after_25_seconds(self):
        expires_at = offer_expiration_for_request(
            ride_mode="negotiate",
            offered_at=self.now,
        )

        self.assertEqual(
            expires_at,
            self.now + timedelta(seconds=25),
        )

    def test_quick_ride_cannot_counter(self):
        offer = self.build_offer(
            request=self.quick_request,
        )

        with self.assertRaises(
            RideOfferModeError
        ):
            counter_offer(
                offer=offer,
                ride_request=self.quick_request,
                counteroffer_fare=Decimal("5200.00"),
                now=self.now,
            )

    def test_negotiated_driver_can_counter_once(self):
        offer = self.build_offer(
            request=self.negotiated_request,
        )

        counter_offer(
            offer=offer,
            ride_request=self.negotiated_request,
            counteroffer_fare=Decimal("5200.00"),
            now=self.now,
        )

        self.assertEqual(
            offer.status,
            "countered",
        )

        self.assertEqual(
            offer.driver_counteroffer_fare,
            Decimal("5200.00"),
        )

        self.assertEqual(
            offer.responded_at,
            self.now,
        )

    def test_second_counter_is_rejected(self):
        offer = self.build_offer(
            request=self.negotiated_request,
        )

        counter_offer(
            offer=offer,
            ride_request=self.negotiated_request,
            counteroffer_fare=Decimal("5200.00"),
            now=self.now,
        )

        with self.assertRaises(
            RideOfferStateError
        ):
            counter_offer(
                offer=offer,
                ride_request=self.negotiated_request,
                counteroffer_fare=Decimal("5400.00"),
                now=self.now,
            )

    def test_counter_below_minimum_is_rejected(self):
        offer = self.build_offer(
            request=self.negotiated_request,
        )

        with self.assertRaises(
            RideOfferFareError
        ):
            counter_offer(
                offer=offer,
                ride_request=self.negotiated_request,
                counteroffer_fare=Decimal("3999.99"),
                now=self.now,
            )

    def test_counter_above_maximum_is_rejected(self):
        offer = self.build_offer(
            request=self.negotiated_request,
        )

        with self.assertRaises(
            RideOfferFareError
        ):
            counter_offer(
                offer=offer,
                ride_request=self.negotiated_request,
                counteroffer_fare=Decimal("6750.01"),
                now=self.now,
            )

    def test_expired_offer_cannot_be_accepted(self):
        offer = self.build_offer(
            request=self.negotiated_request,
            expires_at=(
                self.now
                - timedelta(seconds=1)
            ),
        )

        with self.assertRaises(
            RideOfferExpiredError
        ):
            accept_offer(
                offer=offer,
                ride_request=self.negotiated_request,
                now=self.now,
            )

        self.assertEqual(
            offer.status,
            "expired",
        )

    def test_declined_offer_cannot_later_be_accepted(self):
        offer = self.build_offer(
            request=self.negotiated_request,
        )

        decline_offer(
            offer=offer,
            ride_request=self.negotiated_request,
            now=self.now,
        )

        with self.assertRaises(
            RideOfferStateError
        ):
            accept_offer(
                offer=offer,
                ride_request=self.negotiated_request,
                now=self.now,
            )

    def test_expire_offer_marks_open_offer_expired(self):
        offer = self.build_offer(
            request=self.negotiated_request,
            expires_at=self.now,
        )

        changed = expire_offer(
            offer=offer,
            now=self.now,
        )

        self.assertTrue(
            changed
        )

        self.assertEqual(
            offer.status,
            "expired",
        )


if __name__ == "__main__":
    unittest.main()