from datetime import UTC, datetime
from decimal import Decimal
import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.main import app


try:
    from app.schemas.trip_stops import (
        TripStopLocationRequest,
        TripStopLocationResponse,
        TripStopWaitClosureResponse,
        TripStopWaitExtensionResponse,
    )
except ImportError:
    TripStopLocationRequest = None
    TripStopLocationResponse = None
    TripStopWaitClosureResponse = None
    TripStopWaitExtensionResponse = None


class TripStopApiContractTests(
    unittest.TestCase
):
    def setUp(self):
        self.paths = app.openapi()[
            "paths"
        ]

    def operation(
        self,
        path,
    ):
        self.assertIn(
            path,
            self.paths,
        )

        self.assertIn(
            "post",
            self.paths[path],
        )

        return self.paths[
            path
        ]["post"]

    def test_stop_location_endpoint_is_registered(self):
        self.operation(
            (
                "/api/v1/trips/"
                "{trip_id}/stop-location"
            )
        )

    def test_depart_endpoint_is_registered(self):
        self.operation(
            (
                "/api/v1/trips/"
                "{trip_id}/stops/current/depart"
            )
        )

    def test_extension_endpoint_is_registered(self):
        self.operation(
            (
                "/api/v1/trips/"
                "{trip_id}/stops/current/extend"
            )
        )

    def test_exit_right_endpoint_is_registered(self):
        self.operation(
            (
                "/api/v1/trips/"
                "{trip_id}/stops/current/exit-right"
            )
        )

    def test_all_four_operations_require_authentication(self):
        paths = [
            (
                "/api/v1/trips/"
                "{trip_id}/stop-location"
            ),
            (
                "/api/v1/trips/"
                "{trip_id}/stops/current/depart"
            ),
            (
                "/api/v1/trips/"
                "{trip_id}/stops/current/extend"
            ),
            (
                "/api/v1/trips/"
                "{trip_id}/stops/current/exit-right"
            ),
        ]

        for path in paths:
            operation = self.operation(
                path
            )

            self.assertTrue(
                operation.get(
                    "security"
                ),
                (
                    f"{path} must require "
                    "authentication."
                ),
            )

    def test_mutating_wait_actions_require_idempotency_key(self):
        paths = [
            (
                "/api/v1/trips/"
                "{trip_id}/stops/current/depart"
            ),
            (
                "/api/v1/trips/"
                "{trip_id}/stops/current/extend"
            ),
            (
                "/api/v1/trips/"
                "{trip_id}/stops/current/exit-right"
            ),
        ]

        for path in paths:
            operation = self.operation(
                path
            )

            headers = {
                parameter["name"]: (
                    parameter
                )
                for parameter
                in operation.get(
                    "parameters",
                    []
                )
                if (
                    parameter.get("in")
                    == "header"
                )
            }

            self.assertIn(
                "Idempotency-Key",
                headers,
            )

            self.assertTrue(
                headers[
                    "Idempotency-Key"
                ]["required"]
            )

    def test_location_request_schema_exists_and_forbids_unknown_fields(self):
        self.assertIsNotNone(
            TripStopLocationRequest,
            (
                "TripStopLocationRequest "
                "must exist."
            ),
        )

        with self.assertRaises(
            ValidationError
        ):
            TripStopLocationRequest(
                sample_id=uuid4(),
                latitude=Decimal(
                    "9.0765000"
                ),
                longitude=Decimal(
                    "7.3986000"
                ),
                horizontal_accuracy_m=(
                    Decimal("10.00")
                ),
                captured_at=datetime(
                    2026,
                    9,
                    25,
                    12,
                    0,
                    tzinfo=UTC,
                ),
                unexpected=True,
            )

    def test_location_request_rejects_invalid_coordinates(self):
        self.assertIsNotNone(
            TripStopLocationRequest,
            (
                "TripStopLocationRequest "
                "must exist."
            ),
        )

        with self.assertRaises(
            ValidationError
        ):
            TripStopLocationRequest(
                sample_id=uuid4(),
                latitude=Decimal(
                    "91"
                ),
                longitude=Decimal(
                    "7.3986000"
                ),
                horizontal_accuracy_m=(
                    Decimal("10")
                ),
                captured_at=datetime(
                    2026,
                    9,
                    25,
                    12,
                    0,
                    tzinfo=UTC,
                ),
            )

    def test_stop_location_response_schema_has_required_shape(self):
        self.assertIsNotNone(
            TripStopLocationResponse,
            (
                "TripStopLocationResponse "
                "must exist."
            ),
        )

        payload = (
            TripStopLocationResponse(
                replayed=False,
                stop_id=uuid4(),
                stop_sequence=1,
                distance_to_stop_m=12.5,
                arrival_candidate_count=2,
                arrival_verified=True,
                arrival_newly_verified=True,
            )
        )

        self.assertEqual(
            set(
                payload.model_dump().keys()
            ),
            {
                "replayed",
                "stop_id",
                "stop_sequence",
                "distance_to_stop_m",
                "arrival_candidate_count",
                "arrival_verified",
                "arrival_newly_verified",
            },
        )

    def test_wait_response_schemas_preserve_money_fields(self):
        self.assertIsNotNone(
            TripStopWaitClosureResponse
        )

        self.assertIsNotNone(
            TripStopWaitExtensionResponse
        )

        stop_id = uuid4()

        closed = (
            TripStopWaitClosureResponse(
                stop_id=stop_id,
                final_billable_seconds=120,
                final_wait_charge=(
                    Decimal("150.00")
                ),
                closed_at=datetime(
                    2026,
                    9,
                    25,
                    12,
                    5,
                    tzinfo=UTC,
                ),
                close_reason="departed",
            )
        )

        extended = (
            TripStopWaitExtensionResponse(
                stop_id=stop_id,
                extension_number=1,
                billable_seconds=420,
                gross_wait_charge=(
                    Decimal("525.00")
                ),
                authorized_until=datetime(
                    2026,
                    9,
                    25,
                    12,
                    15,
                    tzinfo=UTC,
                ),
            )
        )

        self.assertEqual(
            closed.final_wait_charge,
            Decimal("150.00"),
        )

        self.assertEqual(
            extended.gross_wait_charge,
            Decimal("525.00"),
        )


if __name__ == "__main__":
    unittest.main()
