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

from app.api.deps import (
    require_roles,
)
from app.db.session import get_db
from app.models.driver_assignment import (
    DriverAssignment,
)
from app.models.driver_profile import (
    DriverProfile,
)
from app.models.trip import Trip
from app.models.trip_event import (
    TripEvent,
)
from app.models.trip_start_verification import (
    TripStartVerification,
)
from app.models.user import User
from app.schemas.trip_verification import (
    TripPinIssueResponse,
    TripPinVerificationResponse,
    TripPinVerifyRequest,
)
from app.schemas.trips import (
    TripStateResponse,
)
from app.services.driver_readiness import (
    get_driver_readiness,
)
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyKeyError,
    execute_idempotently,
)
from app.services.ride_assignment import (
    RideAssignmentEligibilityError,
    ensure_driver_vehicle_eligible,
)
from app.services.trip_state import (
    TripTransitionError,
    transition_trip,
)
from app.services.trip_verification import (
    TripPinAlreadyVerifiedError,
    TripPinExpiredError,
    TripPinInvalidatedError,
    TripPinLockedError,
    TripPinStateError,
    TripStartAuthorizationError,
    check_trip_start_pin,
    ensure_trip_start_authorized,
    invalidate_trip_start_verification,
    issue_trip_start_pin,
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
                "Active assignment "
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

    return assignment


def _require_active_driver(
    *,
    assignment: DriverAssignment,
    driver_id: UUID,
) -> None:
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
                "this action."
            ),
        )


def _lock_verification(
    *,
    db: Session,
    trip_id: UUID,
    assignment_id: UUID,
) -> TripStartVerification | None:
    return db.scalar(
        select(
            TripStartVerification
        )
        .where(
            TripStartVerification.trip_id
            == trip_id,
            TripStartVerification
            .assignment_id
            == assignment_id,
        )
        .with_for_update()
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


def _verification_payload(
    *,
    verified: bool,
    attempt_count: int,
    attempts_remaining: int,
    locked_until,
) -> dict:
    return (
        TripPinVerificationResponse(
            verified=verified,
            attempt_count=(
                attempt_count
            ),
            attempts_remaining=(
                attempts_remaining
            ),
            locked_until=(
                locked_until
            ),
        )
        .model_dump(
            mode="json"
        )
    )


def _recheck_driver_and_vehicle(
    *,
    db: Session,
    assignment: DriverAssignment,
) -> None:
    driver_profile = db.get(
        DriverProfile,
        assignment.driver_id,
    )

    if driver_profile is None:
        raise (
            RideAssignmentEligibilityError(
                "Driver profile does "
                "not exist."
            )
        )

    readiness = (
        get_driver_readiness(
            db=db,
            driver_profile=(
                driver_profile
            ),
        )
    )

    ensure_driver_vehicle_eligible(
        readiness=readiness,
        driver_is_online=bool(
            driver_profile.is_online
        ),
        vehicle_id=(
            assignment.vehicle_id
        ),
    )


def _add_pin_event(
    *,
    db: Session,
    trip: Trip,
    actor_user_id: UUID,
    event_type: str,
    event_data: dict | None = None,
) -> None:
    db.add(
        TripEvent(
            ride_request_id=(
                trip.ride_request_id
            ),
            trip_id=trip.id,
            actor_user_id=(
                actor_user_id
            ),
            event_type=event_type,
            event_data=event_data,
        )
    )


def _raise_verification_error(
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
        TripPinLockedError,
    ):
        raise HTTPException(
            status_code=423,
            detail=str(exc),
        ) from exc

    if isinstance(
        exc,
        RideAssignmentEligibilityError,
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail=str(exc),
        ) from exc

    if isinstance(
        exc,
        (
            TripPinAlreadyVerifiedError,
            TripPinExpiredError,
            TripPinInvalidatedError,
            TripPinStateError,
            TripStartAuthorizationError,
            TripTransitionError,
            IdempotencyConflictError,
            IdempotencyInProgressError,
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
    "/{trip_id}/start-pin",
    response_model=(
        TripPinIssueResponse
    ),
)
def issue_start_pin(
    trip_id: UUID,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("rider")
    ),
):
    trip = _lock_trip_or_404(
        db=db,
        trip_id=trip_id,
    )

    if (
        trip.rider_id
        != current_user.id
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail=(
                "Only the rider who owns "
                "this trip may request "
                "the trip PIN."
            ),
        )

    assignment = (
        _lock_active_assignment(
            db=db,
            trip=trip,
        )
    )

    existing = _lock_verification(
        db=db,
        trip_id=trip.id,
        assignment_id=(
            assignment.id
        ),
    )

    try:
        issued = (
            issue_trip_start_pin(
                trip=trip,
                assignment=assignment,
                existing_verification=(
                    existing
                ),
            )
        )

        if existing is None:
            db.add(
                issued.verification
            )

        _add_pin_event(
            db=db,
            trip=trip,
            actor_user_id=(
                current_user.id
            ),
            event_type=(
                "trip_start_pin_issued"
            ),
            event_data={
                "assignment_id": str(
                    assignment.id
                ),
                "expires_at": (
                    issued
                    .verification
                    .expires_at
                    .isoformat()
                ),
            },
        )

        db.commit()

        return TripPinIssueResponse(
            trip_id=trip.id,
            assignment_id=(
                assignment.id
            ),
            pin=issued.pin,
            expires_at=(
                issued.verification
                .expires_at
            ),
        )

    except (
        TripPinStateError,
    ) as exc:
        db.rollback()

        _raise_verification_error(
            exc=exc,
        )


@router.post(
    "/{trip_id}/verify-pin",
    response_model=(
        TripPinVerificationResponse
    ),
)
def verify_start_pin(
    trip_id: UUID,
    payload: TripPinVerifyRequest,
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
            _lock_active_assignment(
                db=db,
                trip=trip,
            )
        )

        _require_active_driver(
            assignment=assignment,
            driver_id=(
                current_user.id
            ),
        )

        verification = (
            _lock_verification(
                db=db,
                trip_id=trip.id,
                assignment_id=(
                    assignment.id
                ),
            )
        )

        if verification is None:
            raise TripPinStateError(
                "Rider has not issued "
                "a trip PIN yet."
            )

        result = (
            check_trip_start_pin(
                verification=(
                    verification
                ),
                submitted_pin=(
                    payload.pin
                ),
            )
        )

        if result.verified:
            event_type = (
                "trip_start_pin_verified"
            )

        else:
            event_type = (
                "trip_start_pin_failed"
            )

        _add_pin_event(
            db=db,
            trip=trip,
            actor_user_id=(
                current_user.id
            ),
            event_type=event_type,
            event_data={
                "attempt_count": (
                    result.attempt_count
                ),
                "attempts_remaining": (
                    result
                    .attempts_remaining
                ),
                "locked_until": (
                    result.locked_until
                    .isoformat()
                    if result.locked_until
                    is not None
                    else None
                ),
            },
        )

        response_body = (
            _verification_payload(
                verified=(
                    result.verified
                ),
                attempt_count=(
                    result.attempt_count
                ),
                attempts_remaining=(
                    result
                    .attempts_remaining
                ),
                locked_until=(
                    result.locked_until
                ),
            )
        )

        return (
            (
                status.HTTP_200_OK
                if result.verified
                else status
                .HTTP_422_UNPROCESSABLE_CONTENT
            ),
            response_body,
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation=(
                "trip_verify_pin"
            ),
            idempotency_key=(
                idempotency_key
            ),
            request_payload={
                "trip_id": str(
                    trip_id
                ),
                "pin": payload.pin,
            },
            action=action,
        )

        db.commit()

        if (
            result.status_code
            != status.HTTP_200_OK
        ):
            raise HTTPException(
                status_code=(
                    result.status_code
                ),
                detail=result.body,
            )

        return result.body

    except HTTPException:
        raise

    except (
        IdempotencyKeyError,
        IdempotencyConflictError,
        IdempotencyInProgressError,
        TripPinAlreadyVerifiedError,
        TripPinExpiredError,
        TripPinInvalidatedError,
        TripPinLockedError,
        TripPinStateError,
    ) as exc:
        db.rollback()

        _raise_verification_error(
            exc=exc,
        )


@router.post(
    "/{trip_id}/start",
    response_model=(
        TripStateResponse
    ),
)
def start_trip(
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
            _lock_active_assignment(
                db=db,
                trip=trip,
            )
        )

        _require_active_driver(
            assignment=assignment,
            driver_id=(
                current_user.id
            ),
        )

        verification = (
            _lock_verification(
                db=db,
                trip_id=trip.id,
                assignment_id=(
                    assignment.id
                ),
            )
        )

        if verification is None:
            raise (
                TripStartAuthorizationError(
                    "Trip PIN has not "
                    "been issued."
                )
            )

        now = datetime.now(UTC)

        ensure_trip_start_authorized(
            trip=trip,
            assignment=assignment,
            verification=verification,
            now=now,
        )

        _recheck_driver_and_vehicle(
            db=db,
            assignment=assignment,
        )

        transition_trip(
            db=db,
            trip=trip,
            target_status="in_progress",
            actor_user_id=(
                current_user.id
            ),
            event_type="trip_started",
            event_data={
                "assignment_id": str(
                    assignment.id
                ),
                "verification_id": str(
                    verification.id
                ),
            },
            now=now,
        )

        invalidate_trip_start_verification(
            verification=verification,
            now=now,
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
                "trip_start"
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
        RideAssignmentEligibilityError,
        TripPinAlreadyVerifiedError,
        TripPinExpiredError,
        TripPinInvalidatedError,
        TripPinLockedError,
        TripPinStateError,
        TripStartAuthorizationError,
        TripTransitionError,
    ) as exc:
        db.rollback()

        _raise_verification_error(
            exc=exc,
        )