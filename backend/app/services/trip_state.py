from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.models.trip_event import (
    TripEvent,
)


TRIP_TRANSITIONS = {
    "matched": {
        "driver_arriving",
    },
    "driver_arriving": {
        "driver_arrived",
    },
    "driver_arrived": {
        "in_progress",
    },
    "in_progress": {
        "completed",
    },
}


TERMINAL_TRIP_STATUSES = {
    "completed",
    "rider_cancelled",
    "rider_no_show",
    "terminated",
}


class TripStateError(
    ValueError
):
    pass


class TripTransitionError(
    TripStateError
):
    pass


class TripArrivalVerificationError(
    TripStateError
):
    pass


def _set_transition_timestamp(
    *,
    trip: Trip,
    target_status: str,
    now: datetime,
) -> None:
    if (
        target_status
        == "driver_arriving"
    ):
        trip.driver_arriving_at = now

    elif (
        target_status
        == "driver_arrived"
    ):
        trip.arrived_at = now

    elif (
        target_status
        == "in_progress"
    ):
        trip.started_at = now

    elif (
        target_status
        == "completed"
    ):
        trip.completed_at = now


def transition_trip(
    *,
    db: Session,
    trip: Trip,
    target_status: str,
    actor_user_id: UUID,
    event_type: str,
    event_data: dict[
        str,
        Any,
    ] | None = None,
    arrival_verified: bool = False,
    now: datetime | None = None,
) -> Trip:
    if now is None:
        now = datetime.now(UTC)

    current_status = trip.status

    if (
        current_status
        in TERMINAL_TRIP_STATUSES
    ):
        raise TripTransitionError(
            "Terminal trip cannot "
            "transition to another state."
        )

    allowed_targets = (
        TRIP_TRANSITIONS.get(
            current_status,
            set(),
        )
    )

    if (
        target_status
        not in allowed_targets
    ):
        raise TripTransitionError(
            (
                "Invalid trip transition: "
                f"{current_status} "
                f"-> {target_status}."
            )
        )

    if (
        target_status
        == "driver_arrived"
        and not arrival_verified
    ):
        raise (
            TripArrivalVerificationError(
                "Driver arrival requires "
                "backend-verified pickup "
                "arrival."
            )
        )

    trip.status = target_status

    _set_transition_timestamp(
        trip=trip,
        target_status=target_status,
        now=now,
    )

    authoritative_event_data = {
        **(
            event_data
            or {}
        ),
        "from_status": (
            current_status
        ),
        "to_status": (
            target_status
        ),
    }

    event = TripEvent(
        ride_request_id=(
            trip.ride_request_id
        ),
        trip_id=trip.id,
        actor_user_id=(
            actor_user_id
        ),
        event_type=event_type,
        event_data=(
            authoritative_event_data
        ),
        created_at=now,
    )

    db.add(
        event
    )

    db.flush()

    return trip