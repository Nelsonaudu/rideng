from datetime import timedelta
from decimal import Decimal
import unittest
from uuid import uuid4

from app.main import app
from app.models.trip_stop import TripStop
from app.services.trip_stop_waiting import (
    authorize_current_stop_wait_extension,
)

try:
    from app.services.trip_stop_waiting import (
        terminate_at_current_stop,
    )
except ImportError:
    terminate_at_current_stop = None

try:
    from app.schemas.trip_stops import (
        CurrentStopStateResponse,
    )
except ImportError:
    CurrentStopStateResponse = None

class Batch9PlanAlignmentTests(
    unittest.TestCase
):
    def fixture(self):
        from tests.test_trip_stop_waiting_lifecycle import (
            TripStopWaitingLifecycleTests,
        )

        case = TripStopWaitingLifecycleTests(
            "test_depart_during_free_wait_closes_at_zero"
        )
        case.setUp()
        return case

    def test_approved_location_path_exists(self):
        paths = app.openapi()["paths"]

        self.assertIn(
            (
                "/api/v1/trips/{trip_id}"
                "/stops/current/location"
            ),
            paths,
        )

        self.assertIn(
            "post",
            paths[
                (
                    "/api/v1/trips/{trip_id}"
                    "/stops/current/location"
                )
            ],
        )

    def test_current_stop_get_exists(self):
        paths = app.openapi()["paths"]

        path = (
            "/api/v1/trips/{trip_id}"
            "/stops/current"
        )

        self.assertIn(
            path,
            paths,
        )

        self.assertIn(
            "get",
            paths[path],
        )

    def test_approved_extend_wait_path_exists(self):
        paths = app.openapi()["paths"]

        path = (
            "/api/v1/trips/{trip_id}"
            "/stops/current/extend-wait"
        )

        self.assertIn(
            path,
            paths,
        )

        self.assertIn(
            "post",
            paths[path],
        )

    def test_approved_end_trip_path_exists(self):
        paths = app.openapi()["paths"]

        path = (
            "/api/v1/trips/{trip_id}"
            "/stops/current/end-trip"
        )

        self.assertIn(
            path,
            paths,
        )

        self.assertIn(
            "post",
            paths[path],
        )

    def test_current_stop_state_schema_exists(self):
        self.assertIsNotNone(
            CurrentStopStateResponse,
            (
                "CurrentStopStateResponse "
                "must exist."
            ),
        )

    def test_current_stop_state_has_live_meter_fields(self):
        self.assertIsNotNone(
            CurrentStopStateResponse
        )

        fields = set(
            CurrentStopStateResponse
            .model_fields
        )

        required = {
            "stop_id",
            "stop_sequence",
            "phase",
            "billable_seconds",
            "gross_wait_charge",
            "authorized_until",
            "driver_exit_right_at",
            "exit_right_available",
            "extension_available",
        }

        self.assertTrue(
            required <= fields,
            (
                "Missing current-stop fields: "
                f"{sorted(required - fields)}"
            ),
        )

    def test_termination_service_exists(self):
        self.assertIsNotNone(
            terminate_at_current_stop,
            (
                "terminate_at_current_stop "
                "must exist."
            ),
        )

    def test_end_trip_terminates_trip_and_assignment(self):
        self.assertIsNotNone(
            terminate_at_current_stop
        )

        case = self.fixture()

        later_stop = TripStop(
            id=uuid4(),
            ride_request_id=(
                case.ride_request_id
            ),
            trip_id=case.trip.id,
            sequence=2,
            stop_type="intermediate",
            address="Later Stop",
            latitude=Decimal(
                "9.0900000"
            ),
            longitude=Decimal(
                "7.4100000"
            ),
            planned_before_matching=True,
        )

        case.db.add(
            later_stop
        )

        now = (
            case.arrived_at
            + timedelta(minutes=10)
        )

        result = (
            terminate_at_current_stop(
                db=case.db,
                trip=case.trip,
                assignment=(
                    case.assignment
                ),
                rider_id=(
                    case.rider_id
                ),
                now=now,
            )
        )

        self.assertEqual(
            case.trip.status,
            "terminated",
        )

        self.assertIsNone(
            case.trip.active_assignment_id
        )

        self.assertEqual(
            case.assignment.status,
            "completed",
        )

        self.assertEqual(
            case.wait.close_reason,
            (
                "intermediate_stop_"
                "wait_timeout"
            ),
        )

        self.assertEqual(
            result.final_billable_seconds,
            420,
        )

        self.assertEqual(
            result.final_wait_charge,
            Decimal("525.00"),
        )

        self.assertIsNone(
            later_stop.arrived_at
        )

        self.assertIsNone(
            later_stop.departed_at
        )

    def test_extension_does_not_remove_earned_exit_right(self):
        self.assertIsNotNone(
            terminate_at_current_stop
        )

        case = self.fixture()

        extension_at = (
            case.arrived_at
            + timedelta(minutes=10)
        )

        authorize_current_stop_wait_extension(
            db=case.db,
            trip=case.trip,
            assignment=case.assignment,
            rider_id=case.rider_id,
            now=extension_at,
        )

        result = (
            terminate_at_current_stop(
                db=case.db,
                trip=case.trip,
                assignment=case.assignment,
                rider_id=case.rider_id,
                now=(
                    extension_at
                    + timedelta(minutes=1)
                ),
            )
        )

        self.assertEqual(
            case.trip.status,
            "terminated",
        )

        self.assertEqual(
            result.final_billable_seconds,
            480,
        )

        self.assertEqual(
            result.final_wait_charge,
            Decimal("600.00"),
        )


if __name__ == "__main__":
    unittest.main()
