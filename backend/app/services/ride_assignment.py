from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.driver_assignment import (
    DriverAssignment,
)
from app.models.driver_profile import (
    DriverProfile,
)
from app.models.ride_offer import (
    RideOffer,
)
from app.models.ride_request import (
    RideRequest,
)
from app.models.trip import Trip
from app.models.trip_event import (
    TripEvent,
)
from app.models.trip_stop import (
    TripStop,
)
from app.services.driver_readiness import (
    DriverReadinessSnapshot,
    get_driver_readiness,
)
from app.services.ride_offers import (
    RideOfferExpiredError,
    RideOfferStateError,
    accept_offer,
)
from app.services.ride_policy import (
    ABUJA_RIDE_TIMING_POLICY,
)


class RideAssignmentError(
    ValueError
):
    pass


class RideAssignmentConflictError(
    RideAssignmentError
):
    pass


class RideAssignmentEligibilityError(
    RideAssignmentError
):
    pass


class RideAssignmentModeError(
    RideAssignmentError
):
    pass


class RideAssignmentOfferError(
    RideAssignmentError
):
    pass


@dataclass(frozen=True)
class RideAssignmentResult:
    ride_request: RideRequest
    offer: RideOffer
    assignment: DriverAssignment
    trip: Trip
    matched_fare: Decimal


def ensure_driver_vehicle_eligible(
    *,
    readiness: DriverReadinessSnapshot,
    driver_is_online: bool,
    vehicle_id: UUID,
) -> None:
    if not driver_is_online:
        raise RideAssignmentEligibilityError(
            "Driver is not currently online."
        )

    if not readiness.online_eligible:
        raise RideAssignmentEligibilityError(
            "Driver is not currently "
            "eligible to receive rides."
        )

    if (
        vehicle_id
        not in readiness
        .eligible_vehicle_ids
    ):
        raise RideAssignmentEligibilityError(
            "Vehicle is not currently "
            "ride eligible."
        )


def matched_fare_for_offer(
    *,
    ride_request: RideRequest,
    offer: RideOffer,
) -> Decimal:
    if (
        ride_request.ride_mode
        == "quick_ride"
    ):
        if offer.status not in {
            "accepted",
            "selected",
        }:
            raise RideAssignmentOfferError(
                "Quick Ride offer has not "
                "been accepted."
            )

        return (
            ride_request.quick_ride_fare
        )

    if (
        ride_request.ride_mode
        != "negotiate"
    ):
        raise RideAssignmentModeError(
            "Unsupported ride mode."
        )

    if offer.status == "accepted":
        if (
            ride_request.rider_offer_fare
            is None
        ):
            raise RideAssignmentOfferError(
                "Negotiated ride has no "
                "rider offer."
            )

        return (
            ride_request.rider_offer_fare
        )

    if offer.status == "countered":
        if (
            offer.driver_counteroffer_fare
            is None
        ):
            raise RideAssignmentOfferError(
                "Countered offer has no "
                "counteroffer fare."
            )

        return (
            offer.driver_counteroffer_fare
        )

    raise RideAssignmentOfferError(
        "Negotiated offer is not "
        "selectable."
    )


def selection_deadline_for_offer(
    *,
    offer: RideOffer,
) -> datetime:
    if offer.responded_at is None:
        raise RideAssignmentOfferError(
            "Offer has no driver response time."
        )

    return (
        offer.responded_at
        + timedelta(
            seconds=(
                ABUJA_RIDE_TIMING_POLICY
                .rider_selection_seconds
            )
        )
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
        raise RideAssignmentConflictError(
            "Ride request does not exist."
        )

    if (
        ride_request.status
        != "searching"
    ):
        raise RideAssignmentConflictError(
            "Ride request is no longer "
            "available for assignment."
        )

    return ride_request


def _lock_offer(
    *,
    db: Session,
    offer_id: UUID,
) -> RideOffer:
    offer = db.scalar(
        select(
            RideOffer
        )
        .where(
            RideOffer.id
            == offer_id
        )
        .with_for_update()
    )

    if offer is None:
        raise RideAssignmentOfferError(
            "Ride offer does not exist."
        )

    return offer


def _validate_driver(
    *,
    db: Session,
    driver_id: UUID,
    vehicle_id: UUID,
) -> None:
    driver_profile = db.get(
        DriverProfile,
        driver_id,
    )

    if driver_profile is None:
        raise RideAssignmentEligibilityError(
            "Driver profile does not exist."
        )

    readiness = (
        get_driver_readiness(
            db=db,
            driver_profile=driver_profile,
        )
    )

    ensure_driver_vehicle_eligible(
        readiness=readiness,
        driver_is_online=bool(
            driver_profile.is_online
        ),
        vehicle_id=vehicle_id,
    )


def close_competing_offers(
    *,
    db: Session,
    ride_request_id: UUID,
    winning_offer_id: UUID,
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

    for candidate in offers:
        if (
            candidate.id
            == winning_offer_id
        ):
            candidate.status = "selected"
            continue

        if candidate.status in {
            "open",
            "accepted",
            "countered",
        }:
            candidate.status = "closed"


def _prepare_trip_for_assignment(
    *,
    db: Session,
    ride_request: RideRequest,
    assignment: DriverAssignment,
    matched_fare: Decimal,
    now: datetime,
) -> tuple[
    Trip,
    bool,
]:
    trip = db.scalar(
        select(
            Trip
        )
        .where(
            Trip.ride_request_id
            == ride_request.id
        )
        .with_for_update()
    )

    if trip is None:
        trip = Trip(
            ride_request_id=(
                ride_request.id
            ),
            active_assignment_id=(
                assignment.id
            ),
            rider_id=(
                ride_request.rider_id
            ),
            status="matched",
            agreed_fare=matched_fare,
            payment_method=(
                ride_request
                .payment_method
            ),
            matched_at=now,
        )

        db.add(
            trip
        )

        try:
            db.flush()

        except IntegrityError as exc:
            raise RideAssignmentConflictError(
                "Ride already has a trip."
            ) from exc

        return (
            trip,
            False,
        )

    if (
        trip.active_assignment_id
        is not None
    ):
        raise RideAssignmentConflictError(
            "Ride already has an "
            "active assignment."
        )

    if (
        trip.status
        != "matched"
    ):
        raise RideAssignmentConflictError(
            "Existing trip cannot "
            "be rematched in its "
            "current state."
        )

    if (
        trip.started_at
        is not None
        or trip.completed_at
        is not None
    ):
        raise RideAssignmentConflictError(
            "Started or completed trip "
            "cannot be rematched."
        )

    trip.active_assignment_id = (
        assignment.id
    )

    trip.status = "matched"
    trip.agreed_fare = matched_fare

    trip.payment_method = (
        ride_request.payment_method
    )

    trip.matched_at = now

    trip.driver_arriving_at = None
    trip.arrived_at = None
    trip.started_at = None
    trip.completed_at = None

    db.flush()

    return (
        trip,
        True,
    )


def _finalize_assignment(
    *,
    db: Session,
    ride_request: RideRequest,
    offer: RideOffer,
    actor_user_id: UUID,
) -> RideAssignmentResult:
    matched_fare = (
        matched_fare_for_offer(
            ride_request=ride_request,
            offer=offer,
        )
    )

    _validate_driver(
        db=db,
        driver_id=offer.driver_id,
        vehicle_id=offer.vehicle_id,
    )

    now = datetime.now(UTC)

    assignment = DriverAssignment(
        ride_request_id=(
            ride_request.id
        ),
        driver_id=offer.driver_id,
        vehicle_id=offer.vehicle_id,
        ride_offer_id=offer.id,
        status="active",
        assigned_at=now,
    )

    db.add(
        assignment
    )

    try:
        db.flush()

    except IntegrityError as exc:
        raise RideAssignmentConflictError(
            "Ride or driver already has "
            "an active assignment."
        ) from exc

    (
        trip,
        is_rematch,
    ) = _prepare_trip_for_assignment(
        db=db,
        ride_request=ride_request,
        assignment=assignment,
        matched_fare=matched_fare,
        now=now,
    )

    stops = db.scalars(
        select(
            TripStop
        )
        .where(
            TripStop.ride_request_id
            == ride_request.id
        )
        .order_by(
            TripStop.sequence.asc()
        )
    ).all()

    for stop in stops:
        stop.trip_id = trip.id

    ride_request.status = "matched"

    ride_request.matched_fare = (
        matched_fare
    )

    close_competing_offers(
        db=db,
        ride_request_id=(
            ride_request.id
        ),
        winning_offer_id=offer.id,
    )

    db.add(
        TripEvent(
            ride_request_id=(
                ride_request.id
            ),
            trip_id=trip.id,
            actor_user_id=(
                actor_user_id
            ),
            event_type=(
                "driver_reassigned"
                if is_rematch
                else "driver_assigned"
            ),
            event_data={
                "assignment_id": str(
                    assignment.id
                ),
                "driver_id": str(
                    assignment.driver_id
                ),
                "vehicle_id": str(
                    assignment.vehicle_id
                ),
                "offer_id": str(
                    offer.id
                ),
                "rematch": (
                    is_rematch
                ),
            },
        )
    )

    db.add(
        TripEvent(
            ride_request_id=(
                ride_request.id
            ),
            trip_id=trip.id,
            actor_user_id=(
                actor_user_id
            ),
            event_type="trip_matched",
            event_data={
                "matched_fare": str(
                    matched_fare
                ),
                "payment_method": (
                    ride_request
                    .payment_method
                ),
                "rematch": (
                    is_rematch
                ),
            },
        )
    )

    db.flush()

    return RideAssignmentResult(
        ride_request=ride_request,
        offer=offer,
        assignment=assignment,
        trip=trip,
        matched_fare=matched_fare,
    )


def assign_quick_ride(
    *,
    db: Session,
    ride_request_id: UUID,
    offer_id: UUID,
    driver_id: UUID,
    now: datetime | None = None,
) -> RideAssignmentResult:
    now = (
        now
        or datetime.now(UTC)
    )

    ride_request = (
        _lock_ride_request(
            db=db,
            ride_request_id=(
                ride_request_id
            ),
        )
    )

    if (
        ride_request.ride_mode
        != "quick_ride"
    ):
        raise RideAssignmentModeError(
            "Ride request is not "
            "a Quick Ride."
        )

    offer = _lock_offer(
        db=db,
        offer_id=offer_id,
    )

    if (
        offer.ride_request_id
        != ride_request.id
    ):
        raise RideAssignmentOfferError(
            "Offer does not belong to "
            "this ride request."
        )

    if offer.driver_id != driver_id:
        raise RideAssignmentOfferError(
            "Offer does not belong to "
            "this driver."
        )

    try:
        accept_offer(
            offer=offer,
            ride_request=ride_request,
            now=now,
        )

    except (
        RideOfferExpiredError,
        RideOfferStateError,
    ) as exc:
        raise RideAssignmentOfferError(
            str(exc)
        ) from exc

    return _finalize_assignment(
        db=db,
        ride_request=ride_request,
        offer=offer,
        actor_user_id=driver_id,
    )


def select_negotiated_offer(
    *,
    db: Session,
    ride_request_id: UUID,
    offer_id: UUID,
    rider_id: UUID,
    now: datetime | None = None,
) -> RideAssignmentResult:
    now = (
        now
        or datetime.now(UTC)
    )

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
        != rider_id
    ):
        raise RideAssignmentConflictError(
            "Rider does not own "
            "this ride request."
        )

    if (
        ride_request.ride_mode
        != "negotiate"
    ):
        raise RideAssignmentModeError(
            "Ride request is not "
            "a negotiated ride."
        )

    offer = _lock_offer(
        db=db,
        offer_id=offer_id,
    )

    if (
        offer.ride_request_id
        != ride_request.id
    ):
        raise RideAssignmentOfferError(
            "Offer does not belong to "
            "this ride request."
        )

    if offer.status not in {
        "accepted",
        "countered",
    }:
        raise RideAssignmentOfferError(
            "Offer is not selectable."
        )

    if (
        now
        > selection_deadline_for_offer(
            offer=offer,
        )
    ):
        raise RideAssignmentOfferError(
            "Rider selection window "
            "has expired."
        )

    return _finalize_assignment(
        db=db,
        ride_request=ride_request,
        offer=offer,
        actor_user_id=rider_id,
    )