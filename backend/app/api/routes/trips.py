from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    require_roles,
)
from app.db.session import get_db
from app.models.driver_assignment import (
    DriverAssignment,
)
from app.models.trip import Trip
from app.models.trip_location_verification import (
    TripLocationVerificationState,
)
from app.models.user import User
from app.schemas.trips import (
    TripStateResponse,
)
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyKeyError,
    execute_idempotently,
)
from app.services.pickup_location import (
    redact_location_for_assignment,
)
from app.services.trip_state import (
    TripArrivalVerificationError,
    TripTransitionError,
    transition_trip,
)


router = APIRouter(
    prefix="/trips",
)


def _trip_payload(
    trip: Trip,
) -> dict:
    return (
        TripStateResponse
        .model_validate(
            trip
        )
        .model_dump(
            mode="json"
        )
    )


def _lock_trip_or_404(
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


def _require_active_driver(
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

    if (
        assignment.status
        != "active"
    ):
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
                "driver may perform "
                "this trip action."
            ),
        )

    return assignment


def _lock_pickup_location_state(
    *,
    db: Session,
    trip_id: UUID,
) -> TripLocationVerificationState | None:
    return db.scalar(
        select(
            TripLocationVerificationState
        )
        .where(
            TripLocationVerificationState
            .trip_id
            == trip_id
        )
        .with_for_update()
    )


def _pickup_arrival_is_verified(
    *,
    db: Session,
    trip_id: UUID,
    assignment_id: UUID,
) -> bool:
    verification_state = (
        _lock_pickup_location_state(
            db=db,
            trip_id=trip_id,
        )
    )

    if verification_state is None:
        return False

    if (
        verification_state.assignment_id
        != assignment_id
    ):
        return False

    return (
        verification_state
        .arrival_verified_at
        is not None
    )


def _raise_trip_error(
    *,
    exc: Exception,
) -> None:
    if isinstance(
        exc,
        IdempotencyKeyError,
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=str(exc),
        ) from exc

    if isinstance(
        exc,
        (
            IdempotencyConflictError,
            IdempotencyInProgressError,
            TripArrivalVerificationError,
            TripTransitionError,
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
    "/{trip_id}/driver-arriving",
    response_model=(
        TripStateResponse
    ),
)
def driver_arriving(
    trip_id: UUID,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
    ),
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("driver")
    ),
):
    def action():
        trip = _lock_trip_or_404(
            db=db,
            trip_id=trip_id,
        )

        _require_active_driver(
            db=db,
            trip=trip,
            driver_id=current_user.id,
        )

        transition_trip(
            db=db,
            trip=trip,
            target_status=(
                "driver_arriving"
            ),
            actor_user_id=(
                current_user.id
            ),
            event_type=(
                "driver_arriving"
            ),
        )

        return (
            status.HTTP_200_OK,
            _trip_payload(
                trip
            ),
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation=(
                "trip_driver_arriving"
            ),
            idempotency_key=(
                idempotency_key
            ),
            request_payload={
                "trip_id": str(
                    trip_id
                ),
            },
            action=action,
        )

        db.commit()

        return result.body

    except (
        IdempotencyKeyError,
        IdempotencyConflictError,
        IdempotencyInProgressError,
        TripArrivalVerificationError,
        TripTransitionError,
    ) as exc:
        db.rollback()

        _raise_trip_error(
            exc=exc,
        )


@router.post(
    "/{trip_id}/arrive",
    response_model=(
        TripStateResponse
    ),
)
def driver_arrived(
    trip_id: UUID,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
    ),
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("driver")
    ),
):
    def action():
        trip = _lock_trip_or_404(
            db=db,
            trip_id=trip_id,
        )

        assignment = (
            _require_active_driver(
                db=db,
                trip=trip,
                driver_id=(
                    current_user.id
                ),
            )
        )

        arrival_verified = (
            _pickup_arrival_is_verified(
                db=db,
                trip_id=trip.id,
                assignment_id=(
                    assignment.id
                ),
            )
        )

        transition_trip(
            db=db,
            trip=trip,
            target_status=(
                "driver_arrived"
            ),
            actor_user_id=(
                current_user.id
            ),
            event_type=(
                "driver_arrived"
            ),
            arrival_verified=(
                arrival_verified
            ),
        )

        return (
            status.HTTP_200_OK,
            _trip_payload(
                trip
            ),
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation=(
                "trip_driver_arrived"
            ),
            idempotency_key=(
                idempotency_key
            ),
            request_payload={
                "trip_id": str(
                    trip_id
                ),
            },
            action=action,
        )

        db.commit()

        return result.body

    except (
        IdempotencyKeyError,
        IdempotencyConflictError,
        IdempotencyInProgressError,
        TripArrivalVerificationError,
        TripTransitionError,
    ) as exc:
        db.rollback()

        _raise_trip_error(
            exc=exc,
        )


@router.post(
    "/{trip_id}/complete",
    response_model=(
        TripStateResponse
    ),
)
def complete_trip(
    trip_id: UUID,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
    ),
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("driver")
    ),
):
    def action():
        trip = _lock_trip_or_404(
            db=db,
            trip_id=trip_id,
        )

        assignment = (
            _require_active_driver(
                db=db,
                trip=trip,
                driver_id=(
                    current_user.id
                ),
            )
        )

        location_state = (
            _lock_pickup_location_state(
                db=db,
                trip_id=trip.id,
            )
        )

        transition_trip(
            db=db,
            trip=trip,
            target_status=(
                "completed"
            ),
            actor_user_id=(
                current_user.id
            ),
            event_type=(
                "trip_completed"
            ),
        )

        redact_location_for_assignment(
            state=location_state,
            assignment_id=(
                assignment.id
            ),
        )

        return (
            status.HTTP_200_OK,
            _trip_payload(
                trip
            ),
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation=(
                "trip_complete"
            ),
            idempotency_key=(
                idempotency_key
            ),
            request_payload={
                "trip_id": str(
                    trip_id
                ),
            },
            action=action,
        )

        db.commit()

        return result.body

    except (
        IdempotencyKeyError,
        IdempotencyConflictError,
        IdempotencyInProgressError,
        TripArrivalVerificationError,
        TripTransitionError,
    ) as exc:
        db.rollback()

        _raise_trip_error(
            exc=exc,
        )