from decimal import Decimal
import unittest

from app.services.ride_policy import (
    ABUJA_RIDE_TIMING_POLICY,
    build_development_fare_band,
    build_fare_band,
)


class RidePolicyTests(unittest.TestCase):
    def test_approved_abuja_timers(self):
        policy = ABUJA_RIDE_TIMING_POLICY

        self.assertEqual(
            policy.quick_driver_seconds,
            10,
        )

        self.assertEqual(
            policy.negotiation_driver_seconds,
            25,
        )

        self.assertEqual(
            policy.rider_selection_seconds,
            30,
        )

        self.assertEqual(
            policy.free_cancel_seconds,
            120,
        )

        self.assertEqual(
            policy.arrival_free_wait_seconds,
            300,
        )

        self.assertEqual(
            policy.stop_free_wait_seconds,
            180,
        )

        self.assertEqual(
            policy.stop_control_seconds,
            600,
        )

        self.assertEqual(
            policy.stop_extension_seconds,
            300,
        )

        self.assertEqual(
            policy.maximum_intermediate_stops,
            4,
        )

    def test_fare_band_uses_expected_relationships(self):
        band = build_fare_band(
            recommended_fare=Decimal("10000"),
            minimum_offer_ratio=Decimal("0.80"),
            quick_priority_ratio=Decimal("1.15"),
            maximum_counter_ratio=Decimal("1.35"),
        )

        self.assertEqual(
            band.minimum_offer_fare,
            Decimal("8000.00"),
        )

        self.assertEqual(
            band.recommended_fare,
            Decimal("10000.00"),
        )

        self.assertEqual(
            band.quick_ride_fare,
            Decimal("11500.00"),
        )

        self.assertEqual(
            band.maximum_counteroffer_fare,
            Decimal("13500.00"),
        )

    def test_quick_ride_is_above_recommended_fare(self):
        band = build_development_fare_band(
            points=[
                (
                    Decimal("9.0765000"),
                    Decimal("7.3986000"),
                ),
                (
                    Decimal("9.0579000"),
                    Decimal("7.4951000"),
                ),
            ]
        )

        self.assertGreater(
            band.quick_ride_fare,
            band.recommended_fare,
        )

    def test_development_quote_is_deterministic(self):
        points = [
            (
                Decimal("9.0765000"),
                Decimal("7.3986000"),
            ),
            (
                Decimal("9.0579000"),
                Decimal("7.4951000"),
            ),
        ]

        first = build_development_fare_band(
            points=points,
        )

        second = build_development_fare_band(
            points=points,
        )

        self.assertEqual(
            first,
            second,
        )

    def test_non_positive_recommended_fare_rejected(self):
        with self.assertRaises(ValueError):
            build_fare_band(
                recommended_fare=Decimal("0"),
                minimum_offer_ratio=Decimal("0.80"),
                quick_priority_ratio=Decimal("1.15"),
                maximum_counter_ratio=Decimal("1.35"),
            )


if __name__ == "__main__":
    unittest.main()