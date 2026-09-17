import unittest
from unittest.mock import (
    Mock,
    patch,
)
from uuid import uuid4

from app.api.routes.trips import (
    complete_trip,
)


class PickupLocationCompletionCleanupTests(
    unittest.TestCase
):
    def test_trip_completion_redacts_assignment_location(
        self,
    ):
        trip_id = uuid4()
        assignment_id = uuid4()
        driver_id = uuid4()

        trip = Mock()
        trip.id = trip_id

        assignment = Mock()
        assignment.id = assignment_id
        assignment.driver_id = driver_id

        location_state = Mock()

        current_user = Mock()
        current_user.id = driver_id

        db = Mock()
        db.scalar.return_value = (
            location_state
        )

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
                "app.api.routes.trips."
                "_lock_trip_or_404",
                return_value=trip,
            ),
            patch(
                "app.api.routes.trips."
                "_require_active_driver",
                return_value=assignment,
            ),
            patch(
                "app.api.routes.trips."
                "transition_trip",
            ),
            patch(
                "app.api.routes.trips."
                "_trip_payload",
                return_value={
                    "id": str(
                        trip_id
                    ),
                    "status": (
                        "completed"
                    ),
                },
            ),
            patch(
                "app.api.routes.trips."
                "execute_idempotently",
                side_effect=run_action,
            ),
            patch(
                "app.api.routes.trips."
                "redact_location_for_assignment"
            ) as redact,
        ):
            complete_trip(
                trip_id=trip_id,
                idempotency_key=(
                    "completion-cleanup-test"
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