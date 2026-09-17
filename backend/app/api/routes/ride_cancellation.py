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
from app.models.ride_offer import RideOffer
from app.models.ride_request import (
    RideRequest,
)
from app.models.trip import Trip
from app.models.trip_event import TripEvent
from app.models.trip_location_verification import (
    TripLocationVerificationState,
)
from app.models.trip_start_verification import (
    TripStartVerification,
)
from app.models.user import User
from app.schemas.ride_cancellation import (
    DriverCancellationRequest,
    DriverCancellationResponse,
    RiderCancellationResponse,
    RiderNoShowResponse,
)
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyKeyError,
    execute_idempotently,
)
from app.services.pickup_location import (
    has_verified_pickup_arrival,
    has_verified_pickup_progress,
    redact_location_for_assignment,
)
from app.services.ride_cancellation import (
    DriverCancellationStateError,
    RiderCancellationStateError,
    RiderNoShowError,
    cancel_driver_assignment_for_rematch,
    cancel_ride_by_rider,
    mark_rider_no_show,
)


ride_router = APIRouter(
    prefix="/rides",
)


trip_router = APIRouter(
    prefix="/trips",
)


def _lock_ride_request(
    *,
    db: Session,
    ride_request_id: UUID,
) -> RideRequest:
    ride_request = db.scalar(
        select(
            RideRequest
        )
        .where(
            RideRequest.id
            == ride_request_id
        )
        .with_for_update()
    )

    if ride_request is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail="Ride request not found.",
        )

    return ride_request


def _lock_trip_by_request(
    *,
    db: Session,
    ride_request_id: UUID,
) -> Trip | None:
    return db.scalar(
        select(
            Trip
        )
        .where(
            Trip.ride_request_id
            == ride_request_id
        )
        .with_for_update()
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


def _lock_assignment(
    *,
    db: Session,
    trip: Trip,
) -> DriverAssignment | None:
    if (
        trip.active_assignment_id
        is None
    ):
        return None

    return db.scalar(
        select(
            DriverAssignment
        )
        .where(
            DriverAssignment.id
            == trip.active_assignment_id
        )
        .with_for_update()
    )


def _lock_offer(
    *,
    db: Session,
    assignment: (
        DriverAssignment | None
    ),
) -> RideOffer | None:
    if (
        assignment is None
        or assignment.ride_offer_id
        is None
    ):
        return None

    return db.scalar(
        select(
            RideOffer
        )
        .where(
            RideOffer.id
            == assignment.ride_offer_id
        )
        .with_for_update()
    )


def _lock_verification(
    *,
    db: Session,
    trip: Trip | None,
    assignment: (
        DriverAssignment | None
    ),
) -> TripStartVerification | None:
    if (
        trip is None
        or assignment is None
    ):
        return None

    return db.scalar(
        select(
            TripStartVerification
        )
        .where(
            TripStartVerification.trip_id
            == trip.id,
            TripStartVerification
            .assignment_id
            == assignment.id,
        )
        .with_for_update()
    )


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


def _pickup_progress_is_verified(
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

    return has_verified_pickup_progress(
        state=verification_state,
        assignment_id=assignment_id,
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

    return has_verified_pickup_arrival(
        state=verification_state,
        assignment_id=assignment_id,
    )


def _close_unmatched_offers(
    *,
    db: Session,
    ride_request_id: UUID,
) -> None:
    offers = db.scalars(
        select(
            RideOffer
        )
        .where(
            RideOffer.ride_request_id
            == ride_request_id
        )
        .with_for_update()
    ).all()

    for offer in offers:
        if offer.status in {
            "open",
            "accepted",
            "countered",
            "selected",
        }:
            offer.status = "closed"


def _add_event(
    *,
    db: Session,
    ride_request_id: UUID,
    trip_id: UUID | None,
    actor_user_id: UUID,
    event_type: str,
    event_data: dict,
) -> None:
    db.add(
        TripEvent(
            ride_request_id=(
                ride_request_id
            ),
            trip_id=trip_id,
            actor_user_id=(
                actor_user_id
            ),
            event_type=event_type,
            event_data=event_data,
        )
    )


def _raise_cancellation_error(
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
            DriverCancellationStateError,
            RiderCancellationStateError,
            RiderNoShowError,
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


@ride_router.post(
    "/{ride_request_id}/cancel",
    response_model=(
        RiderCancellationResponse
    ),
)
def cancel_rider_ride(
    ride_request_id: UUID,
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
        ride_request = (
            _lock_ride_request(
                db=db,
                ride_request_id=(
                    ride_request_id
                ),
            )
        )

        if (
            ride_request.rider_id
            != current_user.id
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail=(
                    "Rider does not own "
                    "this ride request."
                ),
            )

        trip = (
            _lock_trip_by_request(
                db=db,
                ride_request_id=(
                    ride_request.id
                ),
            )
        )

        assignment = (
            _lock_assignment(
                db=db,
                trip=trip,
            )
            if trip is not None
            else None
        )

        offer = _lock_offer(
            db=db,
            assignment=assignment,
        )

        verification = (
            _lock_verification(
                db=db,
                trip=trip,
                assignment=assignment,
            )
        )

        location_state = None
        progress_verified = False

        if (
            trip is not None
            and assignment is not None
        ):
            location_state = (
                _lock_pickup_location_state(
                    db=db,
                    trip_id=trip.id,
                )
            )

            progress_verified = (
                has_verified_pickup_progress(
                    state=location_state,
                    assignment_id=(
                        assignment.id
                    ),
                )
            )

        result = cancel_ride_by_rider(
            ride_request=ride_request,
            trip=trip,
            assignment=assignment,
            offer=offer,
            verification=verification,
            driver_progress_verified=(
                progress_verified
            ),
        )

        if assignment is not None:
            redact_location_for_assignment(
                state=location_state,
                assignment_id=(
                    assignment.id
                ),
            )

        _close_unmatched_offers(
            db=db,
            ride_request_id=(
                ride_request.id
            ),
        )

        _add_event(
            db=db,
            ride_request_id=(
                ride_request.id
            ),
            trip_id=(
                trip.id
                if trip is not None
                else None
            ),
            actor_user_id=(
                current_user.id
            ),
            event_type="rider_cancelled",
            event_data={
                "cancellation_fee_eligible": (
                    result
                    .cancellation_fee_eligible
                ),
                "driver_progress_verified": (
                    progress_verified
                ),
                "assignment_id": (
                    str(
                        assignment.id
                    )
                    if assignment
                    is not None
                    else None
                ),
            },
        )

        body = (
            RiderCancellationResponse(
                ride_request_id=(
                    ride_request.id
                ),
                trip_id=(
                    trip.id
                    if trip is not None
                    else None
                ),
                ride_request_status=(
                    ride_request.status
                ),
                trip_status=(
                    trip.status
                    if trip is not None
                    else None
                ),
                cancellation_fee_eligible=(
                    result
                    .cancellation_fee_eligible
                ),
            )
            .model_dump(
                mode="json"
            )
        )

        return (
            status.HTTP_200_OK,
            body,
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation="rider_cancel_ride",
            idempotency_key=(
                idempotency_key
            ),
            request_payload={
                "ride_request_id": str(
                    ride_request_id
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
        RiderCancellationStateError,
    ) as exc:
        db.rollback()

        _raise_cancellation_error(
            exc=exc,
        )


@trip_router.post(
    "/{trip_id}/driver-cancel",
    response_model=(
        DriverCancellationResponse
    ),
)
def cancel_driver_assignment(
    trip_id: UUID,
    payload: DriverCancellationRequest,
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
        trip = _lock_trip(
            db=db,
            trip_id=trip_id,
        )

        ride_request = (
            _lock_ride_request(
                db=db,
                ride_request_id=(
                    trip.ride_request_id
                ),
            )
        )

        assignment = (
            _lock_assignment(
                db=db,
                trip=trip,
            )
        )

        if assignment is None:
            raise (
                DriverCancellationStateError(
                    "Trip has no active "
                    "assignment."
                )
            )

        if (
            assignment.driver_id
            != current_user.id
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail=(
                    "Only the assigned "
                    "driver may cancel "
                    "this assignment."
                ),
            )

        offer = _lock_offer(
            db=db,
            assignment=assignment,
        )

        verification = (
            _lock_verification(
                db=db,
                trip=trip,
                assignment=assignment,
            )
        )

        location_state = (
            _lock_pickup_location_state(
                db=db,
                trip_id=trip.id,
            )
        )

        cancel_driver_assignment_for_rematch(
            ride_request=ride_request,
            trip=trip,
            assignment=assignment,
            offer=offer,
            verification=verification,
            reason=payload.reason,
        )

        redact_location_for_assignment(
            state=location_state,
            assignment_id=(
                assignment.id
            ),
        )

        _add_event(
            db=db,
            ride_request_id=(
                ride_request.id
            ),
            trip_id=trip.id,
            actor_user_id=(
                current_user.id
            ),
            event_type=(
                "driver_cancelled"
            ),
            event_data={
                "assignment_id": str(
                    assignment.id
                ),
                "reason": (
                    payload.reason
                ),
                "rider_charged": False,
            },
        )

        _add_event(
            db=db,
            ride_request_id=(
                ride_request.id
            ),
            trip_id=trip.id,
            actor_user_id=(
                current_user.id
            ),
            event_type=(
                "rematching_requested"
            ),
            event_data={
                "previous_assignment_id": str(
                    assignment.id
                ),
            },
        )

        body = (
            DriverCancellationResponse(
                ride_request_id=(
                    ride_request.id
                ),
                trip_id=trip.id,
                assignment_id=(
                    assignment.id
                ),
                ride_request_status=(
                    ride_request.status
                ),
                rematching=True,
            )
            .model_dump(
                mode="json"
            )
        )

        return (
            status.HTTP_200_OK,
            body,
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation=(
                "driver_cancel_assignment"
            ),
            idempotency_key=(
                idempotency_key
            ),
            request_payload={
                "trip_id": str(
                    trip_id
                ),
                "reason": (
                    payload.reason
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
        DriverCancellationStateError,
    ) as exc:
        db.rollback()

        _raise_cancellation_error(
            exc=exc,
        )


@trip_router.post(
    "/{trip_id}/rider-no-show",
    response_model=(
        RiderNoShowResponse
    ),
)
def declare_rider_no_show(
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
        trip = _lock_trip(
            db=db,
            trip_id=trip_id,
        )

        ride_request = (
            _lock_ride_request(
                db=db,
                ride_request_id=(
                    trip.ride_request_id
                ),
            )
        )

        assignment = (
            _lock_assignment(
                db=db,
                trip=trip,
            )
        )

        if assignment is None:
            raise RiderNoShowError(
                "Trip has no active "
                "driver assignment."
            )

        if (
            assignment.driver_id
            != current_user.id
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail=(
                    "Only the assigned "
                    "driver may declare "
                    "rider no-show."
                ),
            )

        verification = (
            _lock_verification(
                db=db,
                trip=trip,
                assignment=assignment,
            )
        )

        location_state = (
            _lock_pickup_location_state(
                db=db,
                trip_id=trip.id,
            )
        )

        arrival_verified = (
            has_verified_pickup_arrival(
                state=location_state,
                assignment_id=(
                    assignment.id
                ),
            )
        )

        result = mark_rider_no_show(
            ride_request=ride_request,
            trip=trip,
            assignment=assignment,
            verification=verification,
            arrival_verified=(
                arrival_verified
            ),
        )

        redact_location_for_assignment(
            state=location_state,
            assignment_id=(
                assignment.id
            ),
        )

        _add_event(
            db=db,
            ride_request_id=(
                ride_request.id
            ),
            trip_id=trip.id,
            actor_user_id=(
                current_user.id
            ),
            event_type="rider_no_show",
            event_data={
                "assignment_id": str(
                    assignment.id
                ),
                "arrival_verified": (
                    arrival_verified
                ),
                "driver_compensation_eligible": (
                    result
                    .driver_compensation_eligible
                ),
            },
        )

        body = (
            RiderNoShowResponse(
                ride_request_id=(
                    ride_request.id
                ),
                trip_id=trip.id,
                trip_status=(
                    trip.status
                ),
                driver_compensation_eligible=(
                    result
                    .driver_compensation_eligible
                ),
            )
            .model_dump(
                mode="json"
            )
        )

        return (
            status.HTTP_200_OK,
            body,
        )

    try:
        result = execute_idempotently(
            db=db,
            user_id=current_user.id,
            operation="rider_no_show",
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
        RiderNoShowError,
    ) as exc:
        db.rollback()

        _raise_cancellation_error(
            exc=exc,
        )