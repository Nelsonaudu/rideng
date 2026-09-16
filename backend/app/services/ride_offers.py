from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ride_offer import RideOffer
from app.models.ride_request import RideRequest
from app.services.ride_policy import (
    ABUJA_RIDE_TIMING_POLICY,
)


class RideOfferError(
    ValueError
):
    pass


class RideOfferStateError(
    RideOfferError
):
    pass


class RideOfferExpiredError(
    RideOfferError
):
    pass


class RideOfferModeError(
    RideOfferError
):
    pass


class RideOfferFareError(
    RideOfferError
):
    pass


def offer_expiration_for_request(
    *,
    ride_mode: str,
    offered_at: datetime,
) -> datetime:
    if ride_mode == "quick_ride":
        seconds = (
            ABUJA_RIDE_TIMING_POLICY
            .quick_driver_seconds
        )

    elif ride_mode == "negotiate":
        seconds = (
            ABUJA_RIDE_TIMING_POLICY
            .negotiation_driver_seconds
        )

    else:
        raise RideOfferModeError(
            "Unsupported ride mode."
        )

    return (
        offered_at
        + timedelta(
            seconds=seconds
        )
    )


def create_driver_offer(
    *,
    db: Session,
    ride_request: RideRequest,
    driver_id: UUID,
    vehicle_id: UUID,
    offered_at: datetime | None = None,
) -> RideOffer:
    if ride_request.status != "searching":
        raise RideOfferStateError(
            "Ride request is not accepting offers."
        )

    offered_at = (
        offered_at
        or datetime.now(UTC)
    )

    offer = RideOffer(
        ride_request_id=(
            ride_request.id
        ),
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        rider_offer_fare=(
            ride_request.rider_offer_fare
            if ride_request.ride_mode
            == "negotiate"
            else None
        ),
        status="open",
        offered_at=offered_at,
        expires_at=(
            offer_expiration_for_request(
                ride_mode=(
                    ride_request.ride_mode
                ),
                offered_at=offered_at,
            )
        ),
    )

    db.add(
        offer
    )

    db.flush()

    return offer


def _ensure_request_searching(
    *,
    ride_request: RideRequest,
) -> None:
    if ride_request.status != "searching":
        raise RideOfferStateError(
            "Ride request is no longer searching."
        )


def _ensure_open_offer(
    *,
    offer: RideOffer,
) -> None:
    if offer.status != "open":
        raise RideOfferStateError(
            "Offer is no longer open."
        )


def _ensure_not_expired(
    *,
    offer: RideOffer,
    now: datetime,
) -> None:
    if now >= offer.expires_at:
        if offer.status == "open":
            offer.status = "expired"

        raise RideOfferExpiredError(
            "Offer has expired."
        )


def accept_offer(
    *,
    offer: RideOffer,
    ride_request: RideRequest,
    now: datetime | None = None,
) -> RideOffer:
    now = (
        now
        or datetime.now(UTC)
    )

    _ensure_request_searching(
        ride_request=ride_request,
    )

    _ensure_open_offer(
        offer=offer,
    )

    _ensure_not_expired(
        offer=offer,
        now=now,
    )

    offer.status = "accepted"
    offer.responded_at = now

    return offer


def counter_offer(
    *,
    offer: RideOffer,
    ride_request: RideRequest,
    counteroffer_fare: Decimal,
    now: datetime | None = None,
) -> RideOffer:
    now = (
        now
        or datetime.now(UTC)
    )

    _ensure_request_searching(
        ride_request=ride_request,
    )

    _ensure_open_offer(
        offer=offer,
    )

    _ensure_not_expired(
        offer=offer,
        now=now,
    )

    if (
        ride_request.ride_mode
        != "negotiate"
    ):
        raise RideOfferModeError(
            "Quick Ride does not permit "
            "driver counteroffers."
        )

    if (
        counteroffer_fare
        < ride_request.minimum_offer_fare
    ):
        raise RideOfferFareError(
            "Counteroffer is below the "
            "minimum permitted fare."
        )

    if (
        counteroffer_fare
        > ride_request
        .maximum_counteroffer_fare
    ):
        raise RideOfferFareError(
            "Counteroffer exceeds the "
            "maximum permitted fare."
        )

    offer.driver_counteroffer_fare = (
        counteroffer_fare
    )

    offer.status = "countered"
    offer.responded_at = now

    return offer


def decline_offer(
    *,
    offer: RideOffer,
    ride_request: RideRequest,
    now: datetime | None = None,
) -> RideOffer:
    now = (
        now
        or datetime.now(UTC)
    )

    _ensure_request_searching(
        ride_request=ride_request,
    )

    _ensure_open_offer(
        offer=offer,
    )

    _ensure_not_expired(
        offer=offer,
        now=now,
    )

    offer.status = "declined"
    offer.responded_at = now

    return offer


def expire_offer(
    *,
    offer: RideOffer,
    now: datetime | None = None,
) -> bool:
    now = (
        now
        or datetime.now(UTC)
    )

    if offer.status != "open":
        return False

    if now < offer.expires_at:
        return False

    offer.status = "expired"

    return True