from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.driver_assignment import (
    DriverAssignment,
)
from app.models.ride_request import (
    RideRequest,
)
from app.models.trip import Trip
from app.models.trip_event import (
    TripEvent,
)
from app.models.trip_location_verification import (
    TripLocationVerificationState,
)
from app.models.user import User
from app.schemas.pickup_location import (
    PickupLocationRequest,
    PickupLocationResponse,
)
from app.services.pickup_location import (
    LocationSampleConflictError,
    LocationSampleRejectedError,
    LocationSampleSequenceError,
    PickupLocationVerificationError,
    process_pickup_location_observation,
)


router = APIRouter(
    prefix="/trips",
)


def _lock_trip(
    *,
    db: Session,
    trip_id: UUID,
) -> Trip:
    trip = db.scalar(
        select(
            Trip
        )
        .where(
            Trip.id
            == trip_id
        )
        .with_for_update()
    )

    if trip is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail="Trip not found.",
        )

    return trip


def _require_active_assignment(
    *,
    db: Session,
    trip: Trip,
    driver_id: UUID,
) -> DriverAssignment:
    if (
        trip.active_assignment_id
        is None
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=(
                "Trip has no active "
                "driver assignment."
            ),
        )

    assignment = db.scalar(
        select(
            DriverAssignment
        )
        .where(
            DriverAssignment.id
            == trip.active_assignment_id
        )
        .with_for_update()
    )

    if assignment is None:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=(
                "Active driver assignment "
                "does not exist."
            ),
        )

    if assignment.status != "active":
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=(
                "Driver assignment "
                "is not active."
            ),
        )

    if (
        assignment.driver_id
        != driver_id
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail=(
                "Only the active assigned "
                "driver may submit "
                "pickup location."
            ),
        )

    return assignment


def _get_ride_request(
    *,
    db: Session,
    trip: Trip,
) -> RideRequest:
    ride_request = db.get(
        RideRequest,
        trip.ride_request_id,
    )

    if ride_request is None:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=(
                "Trip ride request "
                "does not exist."
            ),
        )

    return ride_request


def _lock_or_create_state(
    *,
    db: Session,
    trip: Trip,
    assignment: DriverAssignment,
) -> TripLocationVerificationState:
    verification_state = db.scalar(
        select(
            TripLocationVerificationState
        )
        .where(
            TripLocationVerificationState
            .trip_id
            == trip.id
        )
        .with_for_update()
    )

    if verification_state is None:
        verification_state = (
            TripLocationVerificationState(
                trip_id=trip.id,
                assignment_id=(
                    assignment.id
                ),
            )
        )

        db.add(
            verification_state
        )

    return verification_state


def _add_verification_event(
    *,
    db: Session,
    trip: Trip,
    assignment: DriverAssignment,
    driver_id: UUID,
    sample_id: UUID,
    event_type: str,
    distance_to_pickup_m: float,
    arrival_candidate_count: int,
) -> None:
    event_data = {
        "assignment_id": str(
            assignment.id
        ),
        "sample_id": str(
            sample_id
        ),
        "verification_method": (
            "multi_sample_b_plus"
        ),
        "distance_to_pickup_m": round(
            distance_to_pickup_m,
            2,
        ),
    }

    if (
        event_type
        == "pickup_arrival_verified"
    ):
        event_data[
            "arrival_candidate_count"
        ] = arrival_candidate_count

    db.add(
        TripEvent(
            ride_request_id=(
                trip.ride_request_id
            ),
            trip_id=trip.id,
            actor_user_id=driver_id,
            event_type=event_type,
            event_data=event_data,
        )
    )


def _raise_location_error(
    *,
    exc: Exception,
) -> None:
    if isinstance(
        exc,
        LocationSampleRejectedError,
    ):
        raise HTTPException(
            status_code=(
                status
                .HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=str(exc),
        ) from exc

    if isinstance(
        exc,
        (
            LocationSampleConflictError,
            LocationSampleSequenceError,
            PickupLocationVerificationError,
        ),
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc

    raise exc


@router.post(
    "/{trip_id}/pickup-location",
    response_model=(
        PickupLocationResponse
    ),
)
def submit_pickup_location(
    trip_id: UUID,
    payload: PickupLocationRequest,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("driver")
    ),
):
    try:
        trip = _lock_trip(
            db=db,
            trip_id=trip_id,
        )

        if trip.status not in {
            "matched",
            "driver_arriving",
        }:
            raise HTTPException(
                status_code=(
                    status.HTTP_409_CONFLICT
                ),
                detail=(
                    "Pickup location "
                    "verification is not "
                    "available in the "
                    "current trip state."
                ),
            )

        assignment = (
            _require_active_assignment(
                db=db,
                trip=trip,
                driver_id=(
                    current_user.id
                ),
            )
        )

        ride_request = (
            _get_ride_request(
                db=db,
                trip=trip,
            )
        )

        verification_state = (
            _lock_or_create_state(
                db=db,
                trip=trip,
                assignment=assignment,
            )
        )

        result = (
            process_pickup_location_observation(
                state=(
                    verification_state
                ),
                assignment_id=(
                    assignment.id
                ),
                pickup_latitude=(
                    ride_request
                    .pickup_latitude
                ),
                pickup_longitude=(
                    ride_request
                    .pickup_longitude
                ),
                sample_id=(
                    payload.sample_id
                ),
                latitude=(
                    payload.latitude
                ),
                longitude=(
                    payload.longitude
                ),
                horizontal_accuracy_m=(
                    payload
                    .horizontal_accuracy_m
                ),
                captured_at=(
                    payload.captured_at
                ),
                reported_speed_mps=(
                    payload
                    .reported_speed_mps
                ),
                is_mocked=(
                    payload.is_mocked
                ),
            )
        )

        if (
            result
            .progress_newly_verified
        ):
            _add_verification_event(
                db=db,
                trip=trip,
                assignment=assignment,
                driver_id=(
                    current_user.id
                ),
                sample_id=(
                    payload.sample_id
                ),
                event_type=(
                    "pickup_progress_verified"
                ),
                distance_to_pickup_m=(
                    result
                    .distance_to_pickup_m
                ),
                arrival_candidate_count=(
                    result
                    .arrival_candidate_count
                ),
            )

        if (
            result
            .arrival_newly_verified
        ):
            _add_verification_event(
                db=db,
                trip=trip,
                assignment=assignment,
                driver_id=(
                    current_user.id
                ),
                sample_id=(
                    payload.sample_id
                ),
                event_type=(
                    "pickup_arrival_verified"
                ),
                distance_to_pickup_m=(
                    result
                    .distance_to_pickup_m
                ),
                arrival_candidate_count=(
                    result
                    .arrival_candidate_count
                ),
            )

        db.commit()

        return PickupLocationResponse(
            replayed=(
                result.replayed
            ),
            distance_to_pickup_m=(
                result
                .distance_to_pickup_m
            ),
            progress_verified=(
                result
                .progress_verified
            ),
            progress_newly_verified=(
                result
                .progress_newly_verified
            ),
            arrival_candidate_count=(
                result
                .arrival_candidate_count
            ),
            arrival_verified=(
                result
                .arrival_verified
            ),
            arrival_newly_verified=(
                result
                .arrival_newly_verified
            ),
        )

    except HTTPException:
        db.rollback()
        raise

    except (
        LocationSampleRejectedError,
        LocationSampleSequenceError,
        LocationSampleConflictError,
        PickupLocationVerificationError,
    ) as exc:
        db.rollback()

        _raise_location_error(
            exc=exc,
        )