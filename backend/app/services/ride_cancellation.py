from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.models.driver_assignment import DriverAssignment
from app.models.ride_offer import RideOffer
from app.models.ride_request import RideRequest
from app.models.trip import Trip
from app.models.trip_start_verification import (
    TripStartVerification,
)
from app.services.trip_verification import (
    invalidate_trip_start_verification,
)


@dataclass(frozen=True)
class CancellationPolicy:
    rider_free_cancel_seconds: int
    rider_no_show_wait_seconds: int


@dataclass(frozen=True)
class RiderCancellationResult:
    cancellation_fee_eligible: bool


@dataclass(frozen=True)
class RiderNoShowResult:
    driver_compensation_eligible: bool


ABUJA_CANCELLATION_POLICY = CancellationPolicy(
    rider_free_cancel_seconds=120,
    rider_no_show_wait_seconds=300,
)


class RideCancellationError(
    ValueError
):
    pass


class DriverCancellationStateError(
    RideCancellationError
):
    pass


class RiderCancellationStateError(
    RideCancellationError
):
    pass


class RiderNoShowError(
    RideCancellationError
):
    pass


def rider_cancellation_fee_eligible(
    *,
    assigned_at: datetime,
    cancelled_at: datetime,
    driver_progress_verified: bool,
    policy: CancellationPolicy = (
        ABUJA_CANCELLATION_POLICY
    ),
) -> bool:
    elapsed_seconds = (
        cancelled_at
        - assigned_at
    ).total_seconds()

    if (
        elapsed_seconds
        <= policy.rider_free_cancel_seconds
    ):
        return False

    if not driver_progress_verified:
        return False

    return True


def _invalidate_verification(
    *,
    verification: (
        TripStartVerification | None
    ),
    now: datetime,
) -> None:
    if verification is None:
        return

    invalidate_trip_start_verification(
        verification=verification,
        now=now,
    )


def cancel_driver_assignment_for_rematch(
    *,
    ride_request: RideRequest,
    trip: Trip,
    assignment: DriverAssignment,
    offer: RideOffer | None,
    verification: (
        TripStartVerification | None
    ),
    reason: str,
    now: datetime | None = None,
) -> None:
    now = (
        now
        or datetime.now(UTC)
    )

    if (
        trip.status
        not in {
            "matched",
            "driver_arriving",
            "driver_arrived",
        }
    ):
        raise (
            DriverCancellationStateError(
                "Driver cancellation cannot "
                "use the normal rematching "
                "flow in the current trip state."
            )
        )

    if (
        assignment.status
        != "active"
    ):
        raise (
            DriverCancellationStateError(
                "Driver assignment is "
                "not active."
            )
        )

    if (
        trip.active_assignment_id
        != assignment.id
    ):
        raise (
            DriverCancellationStateError(
                "Assignment is not the "
                "trip's active assignment."
            )
        )

    assignment.status = "cancelled"
    assignment.cancelled_at = now
    assignment.cancellation_reason = (
        reason
    )

    if (
        offer is not None
        and offer.status
        not in {
            "declined",
            "expired",
            "closed",
        }
    ):
        offer.status = "closed"

    _invalidate_verification(
        verification=verification,
        now=now,
    )

    ride_request.status = "searching"
    ride_request.matched_fare = None

    trip.active_assignment_id = None
    trip.status = "matched"

    trip.driver_arriving_at = None
    trip.arrived_at = None
    trip.started_at = None
    trip.completed_at = None


def cancel_ride_by_rider(
    *,
    ride_request: RideRequest,
    trip: Trip | None,
    assignment: (
        DriverAssignment | None
    ),
    offer: RideOffer | None,
    verification: (
        TripStartVerification | None
    ),
    driver_progress_verified: bool,
    now: datetime | None = None,
) -> RiderCancellationResult:
    now = (
        now
        or datetime.now(UTC)
    )

    if ride_request.status not in {
        "requested",
        "searching",
        "matched",
    }:
        raise RiderCancellationStateError(
            "Ride request cannot be "
            "cancelled in its current state."
        )

    if (
        trip is not None
        and trip.status
        in {
            "in_progress",
            "completed",
            "rider_cancelled",
            "rider_no_show",
            "terminated",
        }
    ):
        raise RiderCancellationStateError(
            "This trip cannot use the "
            "normal rider cancellation flow."
        )

    cancellation_fee_eligible = False

    if (
        assignment is not None
        and assignment.status
        == "active"
    ):
        cancellation_fee_eligible = (
            rider_cancellation_fee_eligible(
                assigned_at=(
                    assignment.assigned_at
                ),
                cancelled_at=now,
                driver_progress_verified=(
                    driver_progress_verified
                ),
            )
        )

        assignment.status = "cancelled"
        assignment.cancelled_at = now

        assignment.cancellation_reason = (
            "rider_cancelled"
        )

    if (
        offer is not None
        and offer.status
        not in {
            "declined",
            "expired",
            "closed",
        }
    ):
        offer.status = "closed"

    _invalidate_verification(
        verification=verification,
        now=now,
    )

    ride_request.status = (
        "rider_cancelled"
    )

    if trip is not None:
        trip.status = "rider_cancelled"
        trip.active_assignment_id = None

    return RiderCancellationResult(
        cancellation_fee_eligible=(
            cancellation_fee_eligible
        ),
    )


def mark_rider_no_show(
    *,
    ride_request: RideRequest,
    trip: Trip,
    assignment: DriverAssignment,
    verification: (
        TripStartVerification | None
    ),
    arrival_verified: bool,
    now: datetime | None = None,
    policy: CancellationPolicy = (
        ABUJA_CANCELLATION_POLICY
    ),
) -> RiderNoShowResult:
    now = (
        now
        or datetime.now(UTC)
    )

    if (
        trip.status
        != "driver_arrived"
    ):
        raise RiderNoShowError(
            "Rider no-show is only "
            "available after verified arrival."
        )

    if (
        not arrival_verified
    ):
        raise RiderNoShowError(
            "Pickup arrival has not "
            "been backend verified."
        )

    if trip.arrived_at is None:
        raise RiderNoShowError(
            "Trip has no authoritative "
            "arrival timestamp."
        )

    elapsed_seconds = (
        now
        - trip.arrived_at
    ).total_seconds()

    if (
        elapsed_seconds
        < policy.rider_no_show_wait_seconds
    ):
        raise RiderNoShowError(
            "The rider free waiting "
            "period has not ended."
        )

    if (
        assignment.status
        != "active"
        or trip.active_assignment_id
        != assignment.id
    ):
        raise RiderNoShowError(
            "Trip does not have the "
            "expected active assignment."
        )

    assignment.status = "completed"

    trip.status = "rider_no_show"
    trip.active_assignment_id = None

    _invalidate_verification(
        verification=verification,
        now=now,
    )

    return RiderNoShowResult(
        driver_compensation_eligible=True,
    )