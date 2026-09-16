from decimal import Decimal
import unittest

from pydantic import ValidationError

from app.schemas.rides import (
    RideLocation,
    RideRequestCreate,
)


class RideRequestSchemaTests(unittest.TestCase):
    def setUp(self):
        self.pickup = RideLocation(
            address="Wuse 2, Abuja",
            latitude=Decimal("9.0765000"),
            longitude=Decimal("7.3986000"),
        )

        self.destination = RideLocation(
            address="Gwarinpa, Abuja",
            latitude=Decimal("9.1099000"),
            longitude=Decimal("7.4042000"),
        )

    def test_quick_ride_rejects_rider_offer(self):
        with self.assertRaises(ValidationError):
            RideRequestCreate(
                ride_mode="quick_ride",
                payment_method="cash",
                pickup=self.pickup,
                destination=self.destination,
                rider_offer_fare=Decimal("5000"),
            )

    def test_negotiated_ride_requires_rider_offer(self):
        with self.assertRaises(ValidationError):
            RideRequestCreate(
                ride_mode="negotiate",
                payment_method="cash",
                pickup=self.pickup,
                destination=self.destination,
            )

    def test_four_intermediate_stops_are_allowed(self):
        stops = [
            RideLocation(
                address=f"Stop {number}",
                latitude=Decimal("9.0800000"),
                longitude=Decimal("7.4000000"),
            )
            for number in range(1, 5)
        ]

        request = RideRequestCreate(
            ride_mode="quick_ride",
            payment_method="cash",
            pickup=self.pickup,
            destination=self.destination,
            planned_stops=stops,
        )

        self.assertEqual(
            len(request.planned_stops),
            4,
        )

    def test_five_intermediate_stops_are_rejected(self):
        stops = [
            RideLocation(
                address=f"Stop {number}",
                latitude=Decimal("9.0800000"),
                longitude=Decimal("7.4000000"),
            )
            for number in range(1, 6)
        ]

        with self.assertRaises(ValidationError):
            RideRequestCreate(
                ride_mode="quick_ride",
                payment_method="cash",
                pickup=self.pickup,
                destination=self.destination,
                planned_stops=stops,
            )

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            RideRequestCreate(
                ride_mode="quick_ride",
                payment_method="cash",
                pickup=self.pickup,
                destination=self.destination,
                driver_id="not-allowed",
            )

    def test_invalid_payment_method_is_rejected(self):
        with self.assertRaises(ValidationError):
            RideRequestCreate(
                ride_mode="quick_ride",
                payment_method="crypto",
                pickup=self.pickup,
                destination=self.destination,
            )


if __name__ == "__main__":
    unittest.main()