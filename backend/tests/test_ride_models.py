import unittest

from app.models.driver_assignment import DriverAssignment
from app.models.idempotency_record import IdempotencyRecord
from app.models.ride_offer import RideOffer
from app.models.ride_request import RideRequest
from app.models.trip import Trip
from app.models.trip_event import TripEvent
from app.models.trip_start_verification import TripStartVerification
from app.models.trip_stop import TripStop
from app.services.ride_types import (
    ASSIGNMENT_STATUSES,
    PAYMENT_METHODS,
    RIDE_MODES,
    RIDE_OFFER_STATUSES,
    RIDE_REQUEST_STATUSES,
    STOP_TYPES,
    TRIP_STATUSES,
)


class RideTypeTests(unittest.TestCase):
    def test_approved_domain_values_are_present(self):
        self.assertEqual(
            RIDE_MODES,
            {
                "quick_ride",
                "negotiate",
            },
        )

        self.assertEqual(
            PAYMENT_METHODS,
            {
                "cash",
                "electronic",
            },
        )

        self.assertIn(
            "searching",
            RIDE_REQUEST_STATUSES,
        )

        self.assertIn(
            "countered",
            RIDE_OFFER_STATUSES,
        )

        self.assertIn(
            "active",
            ASSIGNMENT_STATUSES,
        )

        self.assertIn(
            "driver_arrived",
            TRIP_STATUSES,
        )

        self.assertEqual(
            STOP_TYPES,
            {
                "pickup",
                "intermediate",
                "destination",
            },
        )


class RideModelShapeTests(unittest.TestCase):
    def test_expected_table_names_exist(self):
        self.assertEqual(
            RideRequest.__tablename__,
            "ride_requests",
        )

        self.assertEqual(
            RideOffer.__tablename__,
            "ride_offers",
        )

        self.assertEqual(
            DriverAssignment.__tablename__,
            "driver_assignments",
        )

        self.assertEqual(
            Trip.__tablename__,
            "trips",
        )

        self.assertEqual(
            TripStop.__tablename__,
            "trip_stops",
        )

        self.assertEqual(
            TripEvent.__tablename__,
            "trip_events",
        )

        self.assertEqual(
            TripStartVerification.__tablename__,
            "trip_start_verifications",
        )

        self.assertEqual(
            IdempotencyRecord.__tablename__,
            "idempotency_records",
        )

    def test_driver_assignment_has_atomicity_indexes(self):
        index_names = {
            index.name
            for index
            in DriverAssignment.__table__.indexes
        }

        self.assertIn(
            "uq_driver_assignments_active_request",
            index_names,
        )

        self.assertIn(
            "uq_driver_assignments_active_driver",
            index_names,
        )


if __name__ == "__main__":
    unittest.main()