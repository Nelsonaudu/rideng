import unittest
from unittest.mock import (
    Mock,
    patch,
)
from uuid import uuid4

from app.api.routes.ride_cancellation import (
    cancel_driver_assignment,
)


class PickupLocationRematchCleanupTests(
    unittest.TestCase
):
    def test_driver_cancellation_redacts_old_assignment_location(
        self,
    ):
        trip_id = uuid4()
        ride_request_id = uuid4()
        assignment_id = uuid4()
        driver_id = uuid4()

        trip = Mock()
        trip.id = trip_id
        trip.ride_request_id = (
            ride_request_id
        )

        ride_request = Mock()
        ride_request.id = (
            ride_request_id
        )
        ride_request.status = "searching"

        assignment = Mock()
        assignment.id = assignment_id
        assignment.driver_id = driver_id

        offer = Mock()
        verification = Mock()
        location_state = Mock()

        current_user = Mock()
        current_user.id = driver_id

        db = Mock()

        result = Mock()
        result.body = {
            "ride_request_id": str(
                ride_request_id
            ),
            "trip_id": str(
                trip_id
            ),
            "assignment_id": str(
                assignment_id
            ),
            "ride_request_status": (
                "searching"
            ),
            "rematching": True,
        }

        def run_action(**kwargs):
            status_code, body = (
                kwargs["action"]()
            )

            response = Mock()
            response.status_code = (
                status_code
            )
            response.body = body

            return response

        with (
            patch(
                "app.api.routes."
                "ride_cancellation."
                "_lock_trip",
                return_value=trip,
            ),
            patch(
                "app.api.routes."
                "ride_cancellation."
                "_lock_ride_request",
                return_value=(
                    ride_request
                ),
            ),
            patch(
                "app.api.routes."
                "ride_cancellation."
                "_lock_assignment",
                return_value=(
                    assignment
                ),
            ),
            patch(
                "app.api.routes."
                "ride_cancellation."
                "_lock_offer",
                return_value=offer,
            ),
            patch(
                "app.api.routes."
                "ride_cancellation."
                "_lock_verification",
                return_value=(
                    verification
                ),
            ),
            patch(
                "app.api.routes."
                "ride_cancellation."
                "_lock_pickup_location_state",
                return_value=(
                    location_state
                ),
            ),
            patch(
                "app.api.routes."
                "ride_cancellation."
                "cancel_driver_assignment_for_rematch",
            ),
            patch(
                "app.api.routes."
                "ride_cancellation."
                "_add_event",
            ),
            patch(
                "app.api.routes."
                "ride_cancellation."
                "execute_idempotently",
                side_effect=run_action,
            ),
            patch(
                "app.api.routes."
                "ride_cancellation."
                "redact_location_for_assignment"
            ) as redact,
        ):
            cancel_driver_assignment(
                trip_id=trip_id,
                payload=Mock(
                    reason="vehicle_issue"
                ),
                idempotency_key=(
                    "rematch-cleanup-test"
                ),
                db=db,
                current_user=(
                    current_user
                ),
            )

        redact.assert_called_once_with(
            state=location_state,
            assignment_id=(
                assignment_id
            ),
        )


if __name__ == "__main__":
    unittest.main()