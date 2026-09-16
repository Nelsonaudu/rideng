from datetime import UTC, datetime
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_user_roles,
    require_roles,
)
from app.db.session import get_db
from app.models.ride_offer import (
    RideOffer,
)
from app.models.ride_request import (
    RideRequest,
)
from app.models.user import User
from app.schemas.rides import (
    RideOfferCounterCreate,
    RideOfferResponse,
    RideRequestCreate,
    RideRequestResponse,
)
from app.services.ride_offers import (
    RideOfferExpiredError,
    RideOfferFareError,
    RideOfferModeError,
    RideOfferStateError,
    accept_offer,
    counter_offer,
    decline_offer,
    expire_offer,
)
from app.services.ride_requests import (
    RiderProfileRequiredError,
    RideFareValidationError,
    create_ride_request,
)


router = APIRouter(
    prefix="/rides",
)


offer_router = APIRouter(
    prefix="/ride-offers",
)


RIDE_READ_STAFF_ROLES = {
    "admin",
    "compliance_agent",
}


def _get_driver_offer_or_404(
    *,
    db: Session,
    offer_id: UUID,
    driver_id: UUID,
) -> RideOffer:
    offer = db.get(
        RideOffer,
        offer_id,
    )

    if offer is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail="Ride offer not found.",
        )

    if offer.driver_id != driver_id:
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail=(
                "You cannot access "
                "another driver's offer."
            ),
        )

    return offer


def _get_offer_request_or_404(
    *,
    db: Session,
    offer: RideOffer,
) -> RideRequest:
    ride_request = db.get(
        RideRequest,
        offer.ride_request_id,
    )

    if ride_request is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=(
                "Ride request not found."
            ),
        )

    return ride_request


def _raise_offer_error(
    *,
    exc: Exception,
) -> None:
    if isinstance(
        exc,
        RideOfferFareError,
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
        RideOfferModeError,
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc

    if isinstance(
        exc,
        (
            RideOfferExpiredError,
            RideOfferStateError,
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
    "",
    response_model=(
        RideRequestResponse
    ),
    status_code=(
        status.HTTP_201_CREATED
    ),
)
def create_ride(
    payload: RideRequestCreate,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("rider")
    ),
):
    try:
        return create_ride_request(
            db=db,
            rider_id=current_user.id,
            payload=payload,
        )

    except RiderProfileRequiredError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail=str(exc),
        ) from exc

    except RideFareValidationError as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=str(exc),
        ) from exc


@router.get(
    "/{ride_request_id}",
    response_model=(
        RideRequestResponse
    ),
)
def get_ride(
    ride_request_id: UUID,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        get_current_user
    ),
):
    ride_request = db.get(
        RideRequest,
        ride_request_id,
    )

    if ride_request is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=(
                "Ride request not found."
            ),
        )

    if (
        ride_request.rider_id
        != current_user.id
    ):
        roles = get_user_roles(
            db=db,
            user_id=current_user.id,
        )

        if not roles.intersection(
            RIDE_READ_STAFF_ROLES
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail=(
                    "You cannot access "
                    "this ride request."
                ),
            )

    return ride_request


@router.get(
    "/{ride_request_id}/offers",
    response_model=list[
        RideOfferResponse
    ],
)
def get_ride_offers(
    ride_request_id: UUID,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        get_current_user
    ),
):
    ride_request = db.get(
        RideRequest,
        ride_request_id,
    )

    if ride_request is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=(
                "Ride request not found."
            ),
        )

    if (
        ride_request.rider_id
        != current_user.id
    ):
        roles = get_user_roles(
            db=db,
            user_id=current_user.id,
        )

        if not roles.intersection(
            RIDE_READ_STAFF_ROLES
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail=(
                    "You cannot access "
                    "offers for this ride."
                ),
            )

    offers = db.scalars(
        select(
            RideOffer
        )
        .where(
            RideOffer.ride_request_id
            == ride_request_id
        )
        .order_by(
            RideOffer.offered_at.asc()
        )
    ).all()

    now = datetime.now(UTC)
    changed = False

    for offer in offers:
        if expire_offer(
            offer=offer,
            now=now,
        ):
            changed = True

    if changed:
        db.commit()

    return offers


@offer_router.get(
    "",
    response_model=list[
        RideOfferResponse
    ],
)
def get_driver_offers(
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("driver")
    ),
):
    offers = db.scalars(
        select(
            RideOffer
        )
        .where(
            RideOffer.driver_id
            == current_user.id
        )
        .order_by(
            RideOffer.offered_at.desc()
        )
    ).all()

    now = datetime.now(UTC)
    changed = False

    for offer in offers:
        if expire_offer(
            offer=offer,
            now=now,
        ):
            changed = True

    if changed:
        db.commit()

    return offers


@offer_router.post(
    "/{offer_id}/accept",
    response_model=(
        RideOfferResponse
    ),
)
def accept_driver_offer(
    offer_id: UUID,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("driver")
    ),
):
    offer = _get_driver_offer_or_404(
        db=db,
        offer_id=offer_id,
        driver_id=current_user.id,
    )

    ride_request = (
        _get_offer_request_or_404(
            db=db,
            offer=offer,
        )
    )

    try:
        accept_offer(
            offer=offer,
            ride_request=ride_request,
        )

        db.commit()
        db.refresh(
            offer
        )

        return offer

    except (
        RideOfferExpiredError,
        RideOfferFareError,
        RideOfferModeError,
        RideOfferStateError,
    ) as exc:
        if (
            offer.status
            == "expired"
        ):
            db.commit()
        else:
            db.rollback()

        _raise_offer_error(
            exc=exc,
        )


@offer_router.post(
    "/{offer_id}/counter",
    response_model=(
        RideOfferResponse
    ),
)
def counter_driver_offer(
    offer_id: UUID,
    payload: RideOfferCounterCreate,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("driver")
    ),
):
    offer = _get_driver_offer_or_404(
        db=db,
        offer_id=offer_id,
        driver_id=current_user.id,
    )

    ride_request = (
        _get_offer_request_or_404(
            db=db,
            offer=offer,
        )
    )

    try:
        counter_offer(
            offer=offer,
            ride_request=ride_request,
            counteroffer_fare=(
                payload
                .counteroffer_fare
            ),
        )

        db.commit()
        db.refresh(
            offer
        )

        return offer

    except (
        RideOfferExpiredError,
        RideOfferFareError,
        RideOfferModeError,
        RideOfferStateError,
    ) as exc:
        if (
            offer.status
            == "expired"
        ):
            db.commit()
        else:
            db.rollback()

        _raise_offer_error(
            exc=exc,
        )


@offer_router.post(
    "/{offer_id}/decline",
    response_model=(
        RideOfferResponse
    ),
)
def decline_driver_offer(
    offer_id: UUID,
    db: Session = Depends(
        get_db
    ),
    current_user: User = Depends(
        require_roles("driver")
    ),
):
    offer = _get_driver_offer_or_404(
        db=db,
        offer_id=offer_id,
        driver_id=current_user.id,
    )

    ride_request = (
        _get_offer_request_or_404(
            db=db,
            offer=offer,
        )
    )

    try:
        decline_offer(
            offer=offer,
            ride_request=ride_request,
        )

        db.commit()
        db.refresh(
            offer
        )

        return offer

    except (
        RideOfferExpiredError,
        RideOfferFareError,
        RideOfferModeError,
        RideOfferStateError,
    ) as exc:
        if (
            offer.status
            == "expired"
        ):
            db.commit()
        else:
            db.rollback()

        _raise_offer_error(
            exc=exc,
        )