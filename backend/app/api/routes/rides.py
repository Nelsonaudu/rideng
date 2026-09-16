from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_user_roles,
    require_roles,
)
from app.db.session import get_db
from app.models.ride_request import (
    RideRequest,
)
from app.models.user import User
from app.schemas.rides import (
    RideRequestCreate,
    RideRequestResponse,
)
from app.services.ride_requests import (
    RiderProfileRequiredError,
    RideFareValidationError,
    create_ride_request,
)


router = APIRouter(
    prefix="/rides",
)


RIDE_READ_STAFF_ROLES = {
    "admin",
    "compliance_agent",
}


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