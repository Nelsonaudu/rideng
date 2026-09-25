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
from app.models.trip_stop_wait_state import (
    TripStopWaitState,
)
from app.models.user import User
from app.schemas.trip_stops import (
    CurrentStopStateResponse,
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
    get_current_intermediate_stop,
    process_current_stop_location,
)
from app.services.trip_stop_waiting import (
    authorize_current_stop_wait_extension,
    depart_current_intermediate_stop,
    gross_wait_charge,
    terminate_at_current_stop,
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
        select(Trip)
        .where(
            Trip.id == trip_id
        )
        .with_for_update()
    )

    if trip is None:
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    return trip


def _require_in_progress(
    *,
    trip: Trip,
) -> None:
    if trip.status != "in_progress":
        raise HTTPException(
            status_code=409,
            detail=(
                "Trip must be in progress."
            ),
        )


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
            status_code=409,
            detail=(
                "Trip has no active "
                "driver assignment."
            ),
        )

    assignment = db.scalar(
        select(DriverAssignment)
        .where(
            DriverAssignment.id
            == trip.active_assignment_id
        )
        .with_for_update()
    )

    if assignment is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Active driver assignment "
                "does not exist."
            ),
        )

    if assignment.status != "active":
        raise HTTPException(
            status_code=409,
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
    assignment = (
        _lock_active_assignment(
            db=db,
            trip=trip,
        )
    )

    if (
        assignment.driver_id
        != driver_id
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Only the active assigned "
                "driver may perform "
                "this stop action."
            ),
        )

    return assignment


def _require_current_stop(
    *,
    db: Session,
    trip: Trip,
    lock: bool,
):
    stop = get_current_intermediate_stop(
        db=db,
        trip_id=trip.id,
        lock=lock,
    )

    if stop is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Trip has no current "
                "intermediate stop."
            ),
        )

    return stop


def _require_trip_rider(
    *,
    trip: Trip,
    rider_id: UUID,
) -> None:
    if trip.rider_id != rider_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Only the rider who owns "
                "this trip may perform "
                "this action."
            ),
        )


def _require_stop_reader(
    *,
    db: Session,
    trip: Trip,
    user_id: UUID,
) -> None:
    if trip.rider_id == user_id:
        return

    assignment = (
        _lock_active_assignment(
            db=db,
            trip=trip,
        )
    )

    if assignment.driver_id != user_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "User is not authorized "
                "to read this stop."
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


def _live_billable_seconds(
    *,
    wait: TripStopWaitState,
    now: datetime,
) -> int:
    seconds = (
        wait.accrued_billable_seconds
    )

    started_at = (
        wait.current_paid_window_started_at
    )

    authorized_until = (
        wait.authorized_until
    )

    if (
        started_at is not None
        and authorized_until is not None
    ):
        effective_end = min(
            now,
            authorized_until,
        )

        if effective_end > started_at:
            seconds += int(
                (
                    effective_end
                    - started_at
                ).total_seconds()
            )

    return max(
        0,
        seconds,
    )


def _current_phase(
    *,
    stop,
    wait,
    now: datetime,
) -> str:
    if stop.arrived_at is None:
        return "en_route"

    if wait is None:
        return "arrived"

    if wait.closed_at is not None:
        return "closed"

    if now < wait.free_wait_ends_at:
        return "free_wait"

    if now < wait.driver_exit_right_at:
        return "paid_wait"

    if (
        wait.current_paid_window_started_at
        is not None
        and wait.authorized_until
        is not None
        and now < wait.authorized_until
        and (
            wait.current_paid_window_started_at
            >= wait.driver_exit_right_at
        )
    ):
        return "extended_wait"

    return "exit_right_available"


def _raise_stop_error(
    *,
    exc: Exception,
) -> None:
    if isinstance(
        exc,
        IdempotencyKeyError,
    ):
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if isinstance(
        exc,
        LocationSampleRejectedError,
    ):
        raise HTTPException(
            status_code=422,
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
            status_code=409,
            detail=str(exc),
        ) from exc

    raise exc


@router.post(
    "/{trip_id}/stops/current/location",
    response_model=(
        TripStopLocationResponse
    ),
)
def submit_current_stop_location(
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

        _require_in_progress(
            trip=trip,
        )

        result = (
            process_current_stop_location(
                db=db,
                trip=trip,
                assignment=assignment,
                rider_id=trip.rider_id,
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


@router.get(
    "/{trip_id}/stops/current",
    response_model=(
        CurrentStopStateResponse
    ),
)
def get_current_stop_state(
    trip_id: UUID,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles(
            "rider",
            "driver",
        )
    ),
):
    trip = db.scalar(
        select(Trip)
        .where(
            Trip.id == trip_id
        )
    )

    if trip is None:
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    _require_stop_reader(
        db=db,
        trip=trip,
        user_id=current_user.id,
    )

    _require_in_progress(
        trip=trip,
    )

    stop = _require_current_stop(
        db=db,
        trip=trip,
        lock=False,
    )

    wait = db.scalar(
        select(TripStopWaitState)
        .where(
            TripStopWaitState.stop_id
            == stop.id
        )
    )

    now = datetime.now(UTC)

    billable_seconds = 0
    gross_charge = Decimal("0.00")

    free_wait_ends_at = None
    authorized_until = None
    exit_right_at = None
    extension_count = 0

    if wait is not None:
        billable_seconds = (
            _live_billable_seconds(
                wait=wait,
                now=now,
            )
        )

        gross_charge = (
            gross_wait_charge(
                billable_seconds=(
                    billable_seconds
                ),
                rate_per_minute=(
                    wait.wait_rate_per_minute
                ),
            )
        )

        free_wait_ends_at = (
            wait.free_wait_ends_at
        )

        authorized_until = (
            wait.authorized_until
        )

        exit_right_at = (
            wait.driver_exit_right_at
        )

        extension_count = (
            wait.extension_count
        )

    exit_right_available = (
        exit_right_at is not None
        and now >= exit_right_at
    )

    extension_available = (
        exit_right_available
        and (
            authorized_until is None
            or now >= authorized_until
        )
    )

    return CurrentStopStateResponse(
        stop_id=stop.id,
        stop_sequence=stop.sequence,
        address=stop.address,
        arrived_at=stop.arrived_at,
        phase=_current_phase(
            stop=stop,
            wait=wait,
            now=now,
        ),
        billable_seconds=(
            billable_seconds
        ),
        gross_wait_charge=(
            gross_charge
        ),
        free_wait_ends_at=(
            free_wait_ends_at
        ),
        authorized_until=(
            authorized_until
        ),
        driver_exit_right_at=(
            exit_right_at
        ),
        exit_right_available=(
            exit_right_available
        ),
        extension_available=(
            extension_available
        ),
        extension_count=(
            extension_count
        ),
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

        _require_in_progress(
            trip=trip,
        )

        result = (
            depart_current_intermediate_stop(
                db=db,
                trip=trip,
                assignment=assignment,
                rider_id=trip.rider_id,
                now=datetime.now(UTC),
            )
        )

        return (
            status.HTTP_200_OK,
            _closure_payload(result),
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
    "/{trip_id}/stops/current/extend-wait",
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

        _require_in_progress(
            trip=trip,
        )

        result = (
            authorize_current_stop_wait_extension(
                db=db,
                trip=trip,
                assignment=assignment,
                rider_id=trip.rider_id,
                now=datetime.now(UTC),
            )
        )

        return (
            status.HTTP_200_OK,
            _extension_payload(result),
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation=(
                "trip_stop_extend_wait"
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
    "/{trip_id}/stops/current/end-trip",
    response_model=(
        TripStopWaitClosureResponse
    ),
)
def end_trip_at_current_stop(
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

        _require_in_progress(
            trip=trip,
        )

        result = (
            terminate_at_current_stop(
                db=db,
                trip=trip,
                assignment=assignment,
                rider_id=trip.rider_id,
                now=datetime.now(UTC),
            )
        )

        return (
            status.HTTP_200_OK,
            _closure_payload(result),
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation=(
                "trip_stop_end_trip"
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
