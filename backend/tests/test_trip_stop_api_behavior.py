from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import (
    get_current_user,
)
from app.db.session import get_db
from app.main import app
from app.models.driver_assignment import (
    DriverAssignment,
)
from app.models.trip import Trip
from app.models.user import User
from app.schemas.trip_stops import (
    TripStopLocationRequest,
)
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyResult,
)
from app.services.location_verification import (
    LocationSampleRejectedError,
)


class FakeScalarResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class RoleSession:
    def __init__(self, roles):
        self.roles = roles

    def scalars(self, statement):
        return FakeScalarResult(
            self.roles
        )


class RouteSession:
    def __init__(
        self,
        *,
        trip=None,
        assignment=None,
    ):
        self.trip = trip
        self.assignment = assignment

        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0

    def scalar(self, statement):
        descriptions = (
            statement.column_descriptions
        )

        entity = None

        if descriptions:
            entity = descriptions[
                0
            ].get("entity")

        if entity is Trip:
            return self.trip

        if entity is DriverAssignment:
            return self.assignment

        return None

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def flush(self):
        self.flush_count += 1


class TripStopApiBehaviorTests(
    unittest.TestCase
):
    def setUp(self):
        from app.api.routes import (
            trip_stops,
        )

        self.routes = trip_stops

        self.client = TestClient(
            app
        )

        self.trip_id = uuid4()
        self.ride_request_id = uuid4()

        self.driver_id = uuid4()
        self.rider_id = uuid4()

        self.assignment_id = uuid4()

        self.driver = User(
            id=self.driver_id,
            first_name="Driver",
            last_name="Test",
            phone_number=(
                "+2348000000001"
            ),
            is_active=True,
        )

        self.rider = User(
            id=self.rider_id,
            first_name="Rider",
            last_name="Test",
            phone_number=(
                "+2348000000002"
            ),
            is_active=True,
        )

        self.trip = Trip(
            id=self.trip_id,
            ride_request_id=(
                self.ride_request_id
            ),
            active_assignment_id=(
                self.assignment_id
            ),
            rider_id=self.rider_id,
            status="in_progress",
            agreed_fare=Decimal(
                "5750.00"
            ),
            payment_method="cash",
            matched_at=datetime.now(
                UTC
            ),
            started_at=datetime.now(
                UTC
            ),
        )

        self.assignment = (
            DriverAssignment(
                id=self.assignment_id,
                ride_request_id=(
                    self.ride_request_id
                ),
                driver_id=self.driver_id,
                vehicle_id=uuid4(),
                status="active",
                assigned_at=datetime.now(
                    UTC
                ),
            )
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    def override_identity(
        self,
        *,
        user,
        roles,
    ):
        role_db = RoleSession(
            roles
        )

        app.dependency_overrides[
            get_current_user
        ] = lambda: user

        app.dependency_overrides[
            get_db
        ] = lambda: role_db

    def location_body(self):
        return {
            "sample_id": str(
                uuid4()
            ),
            "latitude": "9.0765000",
            "longitude": "7.3986000",
            "horizontal_accuracy_m": (
                "10.00"
            ),
            "captured_at": (
                datetime.now(
                    UTC
                ).isoformat()
            ),
        }

    def test_unauthenticated_stop_location_is_401(self):
        response = self.client.post(
            (
                f"/api/v1/trips/"
                f"{self.trip_id}/"
                "stop-location"
            ),
            json=self.location_body(),
        )

        self.assertEqual(
            response.status_code,
            401,
        )

    def test_rider_cannot_submit_driver_location(self):
        self.override_identity(
            user=self.rider,
            roles={"rider"},
        )

        response = self.client.post(
            (
                f"/api/v1/trips/"
                f"{self.trip_id}/"
                "stop-location"
            ),
            json=self.location_body(),
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_rider_cannot_depart_stop(self):
        self.override_identity(
            user=self.rider,
            roles={"rider"},
        )

        response = self.client.post(
            (
                f"/api/v1/trips/"
                f"{self.trip_id}/"
                "stops/current/depart"
            ),
            headers={
                "Idempotency-Key": (
                    "rider-depart-test"
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_driver_cannot_authorize_extension(self):
        self.override_identity(
            user=self.driver,
            roles={"driver"},
        )

        response = self.client.post(
            (
                f"/api/v1/trips/"
                f"{self.trip_id}/"
                "stops/current/extend"
            ),
            headers={
                "Idempotency-Key": (
                    "driver-extend-test"
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_rider_cannot_exercise_driver_exit_right(self):
        self.override_identity(
            user=self.rider,
            roles={"rider"},
        )

        response = self.client.post(
            (
                f"/api/v1/trips/"
                f"{self.trip_id}/"
                "stops/current/exit-right"
            ),
            headers={
                "Idempotency-Key": (
                    "rider-exit-test"
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_wrong_driver_is_rejected_from_active_assignment(self):
        db = RouteSession(
            trip=self.trip,
            assignment=self.assignment,
        )

        with self.assertRaises(
            HTTPException
        ) as context:
            self.routes._require_driver_assignment(
                db=db,
                trip=self.trip,
                driver_id=uuid4(),
            )

        self.assertEqual(
            context.exception.status_code,
            403,
        )

    def test_wrong_rider_is_rejected(self):
        with self.assertRaises(
            HTTPException
        ) as context:
            self.routes._require_trip_rider(
                trip=self.trip,
                rider_id=uuid4(),
            )

        self.assertEqual(
            context.exception.status_code,
            403,
        )

    def test_location_success_commits_once(self):
        db = RouteSession(
            trip=self.trip,
            assignment=self.assignment,
        )

        payload = (
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
                captured_at=datetime.now(
                    UTC
                ),
            )
        )

        service_result = (
            SimpleNamespace(
                replayed=False,
                stop_id=uuid4(),
                stop_sequence=1,
                distance_to_stop_m=12.5,
                arrival_candidate_count=1,
                arrival_verified=False,
                arrival_newly_verified=False,
            )
        )

        with patch.object(
            self.routes,
            "process_current_stop_location",
            return_value=service_result,
        ) as process:
            response = (
                self.routes.submit_stop_location(
                    trip_id=self.trip_id,
                    payload=payload,
                    db=db,
                    current_user=(
                        self.driver
                    ),
                )
            )

        self.assertEqual(
            db.commit_count,
            1,
        )

        self.assertEqual(
            db.rollback_count,
            0,
        )

        self.assertEqual(
            response[
                "arrival_candidate_count"
            ],
            1,
        )

        call = process.call_args.kwargs

        self.assertIs(
            call["trip"],
            self.trip,
        )

        self.assertIs(
            call["assignment"],
            self.assignment,
        )

        self.assertEqual(
            call["rider_id"],
            self.rider_id,
        )

    def test_location_domain_failure_rolls_back(self):
        db = RouteSession(
            trip=self.trip,
            assignment=self.assignment,
        )

        payload = (
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
                captured_at=datetime.now(
                    UTC
                ),
            )
        )

        with patch.object(
            self.routes,
            "process_current_stop_location",
            side_effect=(
                LocationSampleRejectedError(
                    "Poor GPS accuracy."
                )
            ),
        ):
            with self.assertRaises(
                HTTPException
            ) as context:
                self.routes.submit_stop_location(
                    trip_id=self.trip_id,
                    payload=payload,
                    db=db,
                    current_user=(
                        self.driver
                    ),
                )

        self.assertEqual(
            context.exception.status_code,
            422,
        )

        self.assertEqual(
            db.commit_count,
            0,
        )

        self.assertEqual(
            db.rollback_count,
            1,
        )

    def test_depart_uses_driver_scoped_idempotency_and_commits(self):
        db = RouteSession(
            trip=self.trip,
            assignment=self.assignment,
        )

        lifecycle_result = (
            SimpleNamespace(
                stop_id=uuid4(),
                final_billable_seconds=120,
                final_wait_charge=(
                    Decimal("150.00")
                ),
                closed_at=datetime.now(
                    UTC
                ),
                close_reason="departed",
            )
        )

        captured = {}

        def fake_execute(
            **kwargs,
        ):
            captured.update(
                kwargs
            )

            status_code, body = (
                kwargs["action"]()
            )

            return IdempotencyResult(
                status_code=(
                    status_code
                ),
                body=body,
                replayed=False,
            )

        with (
            patch.object(
                self.routes,
                "depart_current_intermediate_stop",
                return_value=(
                    lifecycle_result
                ),
            ),
            patch.object(
                self.routes,
                "execute_idempotently",
                side_effect=fake_execute,
            ),
        ):
            response = (
                self.routes.depart_current_stop(
                    trip_id=self.trip_id,
                    idempotency_key=(
                        "depart-001"
                    ),
                    db=db,
                    current_user=(
                        self.driver
                    ),
                )
            )

        self.assertEqual(
            captured["user_id"],
            self.driver_id,
        )

        self.assertEqual(
            captured["operation"],
            "trip_stop_depart",
        )

        self.assertEqual(
            captured[
                "request_payload"
            ],
            {
                "trip_id": str(
                    self.trip_id
                ),
            },
        )

        self.assertEqual(
            db.commit_count,
            1,
        )

        self.assertEqual(
            db.rollback_count,
            0,
        )

        self.assertEqual(
            response[
                "final_wait_charge"
            ],
            "150.00",
        )

    def test_extension_uses_rider_scoped_idempotency(self):
        db = RouteSession(
            trip=self.trip,
            assignment=self.assignment,
        )

        lifecycle_result = (
            SimpleNamespace(
                stop_id=uuid4(),
                extension_number=1,
                billable_seconds=420,
                gross_wait_charge=(
                    Decimal("525.00")
                ),
                authorized_until=(
                    datetime.now(UTC)
                ),
            )
        )

        captured = {}

        def fake_execute(
            **kwargs,
        ):
            captured.update(
                kwargs
            )

            status_code, body = (
                kwargs["action"]()
            )

            return IdempotencyResult(
                status_code=status_code,
                body=body,
                replayed=False,
            )

        with (
            patch.object(
                self.routes,
                "authorize_current_stop_wait_extension",
                return_value=(
                    lifecycle_result
                ),
            ),
            patch.object(
                self.routes,
                "execute_idempotently",
                side_effect=fake_execute,
            ),
        ):
            self.routes.extend_current_stop_wait(
                trip_id=self.trip_id,
                idempotency_key=(
                    "extend-001"
                ),
                db=db,
                current_user=(
                    self.rider
                ),
            )

        self.assertEqual(
            captured["user_id"],
            self.rider_id,
        )

        self.assertEqual(
            captured["operation"],
            "trip_stop_extend",
        )

        self.assertEqual(
            db.commit_count,
            1,
        )

        self.assertEqual(
            db.rollback_count,
            0,
        )

    def test_exit_right_uses_driver_scoped_idempotency(self):
        db = RouteSession(
            trip=self.trip,
            assignment=self.assignment,
        )

        lifecycle_result = (
            SimpleNamespace(
                stop_id=uuid4(),
                final_billable_seconds=420,
                final_wait_charge=(
                    Decimal("525.00")
                ),
                closed_at=datetime.now(
                    UTC
                ),
                close_reason=(
                    "driver_exit_right"
                ),
            )
        )

        captured = {}

        def fake_execute(
            **kwargs,
        ):
            captured.update(
                kwargs
            )

            status_code, body = (
                kwargs["action"]()
            )

            return IdempotencyResult(
                status_code=status_code,
                body=body,
                replayed=False,
            )

        with (
            patch.object(
                self.routes,
                "exercise_current_stop_exit_right",
                return_value=(
                    lifecycle_result
                ),
            ),
            patch.object(
                self.routes,
                "execute_idempotently",
                side_effect=fake_execute,
            ),
        ):
            self.routes.exercise_stop_exit_right(
                trip_id=self.trip_id,
                idempotency_key=(
                    "exit-001"
                ),
                db=db,
                current_user=(
                    self.driver
                ),
            )

        self.assertEqual(
            captured["user_id"],
            self.driver_id,
        )

        self.assertEqual(
            captured["operation"],
            "trip_stop_exit_right",
        )

        self.assertEqual(
            db.commit_count,
            1,
        )

        self.assertEqual(
            db.rollback_count,
            0,
        )

    def test_idempotency_conflict_rolls_back(self):
        db = RouteSession(
            trip=self.trip,
            assignment=self.assignment,
        )

        with patch.object(
            self.routes,
            "execute_idempotently",
            side_effect=(
                IdempotencyConflictError(
                    "Key conflict."
                )
            ),
        ):
            with self.assertRaises(
                HTTPException
            ) as context:
                self.routes.depart_current_stop(
                    trip_id=self.trip_id,
                    idempotency_key=(
                        "duplicate-key"
                    ),
                    db=db,
                    current_user=(
                        self.driver
                    ),
                )

        self.assertEqual(
            context.exception.status_code,
            409,
        )

        self.assertEqual(
            db.commit_count,
            0,
        )

        self.assertEqual(
            db.rollback_count,
            1,
        )


if __name__ == "__main__":
    unittest.main()
