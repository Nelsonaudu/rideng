from datetime import UTC, datetime
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

from app.api.deps import require_roles
from app.db.session import get_db
from app.models.driver_assignment import (
    DriverAssignment,
)
from app.models.trip import Trip
from app.models.user import User
from app.schemas.trip_stops import (
    TripStopLocationRequest,
    TripStopLocationResponse,
    TripStopWaitClosureResponse,
    TripStopWaitExtensionResponse,
)
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyKeyError,
    execute_idempotently,
)
from app.services.location_verification import (
    LocationSample,
    LocationSampleConflictError,
    LocationSampleRejectedError,
    LocationSampleSequenceError,
)
from app.services.trip_stop_location import (
    process_current_stop_location,
)
from app.services.trip_stop_waiting import (
    authorize_current_stop_wait_extension,
    depart_current_intermediate_stop,
    exercise_current_stop_exit_right,
)


router = APIRouter(
    prefix="/trips",
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
            Trip.id == trip_id
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


def _lock_active_assignment(
    *,
    db: Session,
    trip: Trip,
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

    return assignment


def _require_driver_assignment(
    *,
    db: Session,
    trip: Trip,
    driver_id: UUID,
) -> DriverAssignment:
    assignment = _lock_active_assignment(
        db=db,
        trip=trip,
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
                "this stop action."
            ),
        )

    return assignment


def _require_trip_rider(
    *,
    trip: Trip,
    rider_id: UUID,
) -> None:
    if trip.rider_id != rider_id:
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail=(
                "Only the rider who owns "
                "this trip may authorize "
                "the stop extension."
            ),
        )


def _location_payload(
    result,
) -> dict:
    return (
        TripStopLocationResponse(
            replayed=result.replayed,
            stop_id=result.stop_id,
            stop_sequence=(
                result.stop_sequence
            ),
            distance_to_stop_m=(
                result.distance_to_stop_m
            ),
            arrival_candidate_count=(
                result
                .arrival_candidate_count
            ),
            arrival_verified=(
                result.arrival_verified
            ),
            arrival_newly_verified=(
                result
                .arrival_newly_verified
            ),
        )
        .model_dump(
            mode="json"
        )
    )


def _closure_payload(
    result,
) -> dict:
    return (
        TripStopWaitClosureResponse(
            stop_id=result.stop_id,
            final_billable_seconds=(
                result
                .final_billable_seconds
            ),
            final_wait_charge=(
                result.final_wait_charge
            ),
            closed_at=result.closed_at,
            close_reason=(
                result.close_reason
            ),
        )
        .model_dump(
            mode="json"
        )
    )


def _extension_payload(
    result,
) -> dict:
    return (
        TripStopWaitExtensionResponse(
            stop_id=result.stop_id,
            extension_number=(
                result.extension_number
            ),
            billable_seconds=(
                result.billable_seconds
            ),
            gross_wait_charge=(
                result.gross_wait_charge
            ),
            authorized_until=(
                result.authorized_until
            ),
        )
        .model_dump(
            mode="json"
        )
    )


def _raise_stop_error(
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
            IdempotencyConflictError,
            IdempotencyInProgressError,
            ValueError,
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
    "/{trip_id}/stop-location",
    response_model=(
        TripStopLocationResponse
    ),
)
def submit_stop_location(
    trip_id: UUID,
    payload: TripStopLocationRequest,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("driver")
    ),
):
    try:
        trip = _lock_trip_or_404(
            db=db,
            trip_id=trip_id,
        )

        assignment = (
            _require_driver_assignment(
                db=db,
                trip=trip,
                driver_id=(
                    current_user.id
                ),
            )
        )

        result = (
            process_current_stop_location(
                db=db,
                trip=trip,
                assignment=assignment,
                rider_id=(
                    trip.rider_id
                ),
                sample=LocationSample(
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
                ),
                now=datetime.now(UTC),
            )
        )

        response = _location_payload(
            result
        )

        db.commit()

        return response

    except HTTPException:
        db.rollback()
        raise

    except (
        LocationSampleRejectedError,
        LocationSampleSequenceError,
        LocationSampleConflictError,
        ValueError,
    ) as exc:
        db.rollback()

        _raise_stop_error(
            exc=exc,
        )


@router.post(
    "/{trip_id}/stops/current/depart",
    response_model=(
        TripStopWaitClosureResponse
    ),
)
def depart_current_stop(
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
            _require_driver_assignment(
                db=db,
                trip=trip,
                driver_id=(
                    current_user.id
                ),
            )
        )

        result = (
            depart_current_intermediate_stop(
                db=db,
                trip=trip,
                assignment=assignment,
                rider_id=(
                    trip.rider_id
                ),
                now=datetime.now(UTC),
            )
        )

        return (
            status.HTTP_200_OK,
            _closure_payload(
                result
            ),
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation=(
                "trip_stop_depart"
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

    except HTTPException:
        db.rollback()
        raise

    except (
        IdempotencyKeyError,
        IdempotencyConflictError,
        IdempotencyInProgressError,
        ValueError,
    ) as exc:
        db.rollback()

        _raise_stop_error(
            exc=exc,
        )


@router.post(
    "/{trip_id}/stops/current/extend",
    response_model=(
        TripStopWaitExtensionResponse
    ),
)
def extend_current_stop_wait(
    trip_id: UUID,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
    ),
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("rider")
    ),
):
    def action():
        trip = _lock_trip_or_404(
            db=db,
            trip_id=trip_id,
        )

        _require_trip_rider(
            trip=trip,
            rider_id=(
                current_user.id
            ),
        )

        assignment = (
            _lock_active_assignment(
                db=db,
                trip=trip,
            )
        )

        result = (
            authorize_current_stop_wait_extension(
                db=db,
                trip=trip,
                assignment=assignment,
                rider_id=(
                    current_user.id
                ),
                now=datetime.now(UTC),
            )
        )

        return (
            status.HTTP_200_OK,
            _extension_payload(
                result
            ),
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation=(
                "trip_stop_extend"
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

    except HTTPException:
        db.rollback()
        raise

    except (
        IdempotencyKeyError,
        IdempotencyConflictError,
        IdempotencyInProgressError,
        ValueError,
    ) as exc:
        db.rollback()

        _raise_stop_error(
            exc=exc,
        )


@router.post(
    "/{trip_id}/stops/current/exit-right",
    response_model=(
        TripStopWaitClosureResponse
    ),
)
def exercise_stop_exit_right(
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
            _require_driver_assignment(
                db=db,
                trip=trip,
                driver_id=(
                    current_user.id
                ),
            )
        )

        result = (
            exercise_current_stop_exit_right(
                db=db,
                trip=trip,
                assignment=assignment,
                rider_id=(
                    trip.rider_id
                ),
                now=datetime.now(UTC),
            )
        )

        return (
            status.HTTP_200_OK,
            _closure_payload(
                result
            ),
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation=(
                "trip_stop_exit_right"
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

    except HTTPException:
        db.rollback()
        raise

    except (
        IdempotencyKeyError,
        IdempotencyConflictError,
        IdempotencyInProgressError,
        ValueError,
    ) as exc:
        db.rollback()

        _raise_stop_error(
            exc=exc,
        )
