from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    ensure_self_or_admin,
    get_current_user,
    require_roles,
)
from app.db.session import get_db
from app.models.driver_profile import DriverProfile
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.driver import (
    DriverOnlineStatusUpdate,
    DriverProfileResponse,
)


router = APIRouter()


@router.get(
    "/drivers/{user_id}",
    response_model=DriverProfileResponse,
)
def get_driver_profile(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_self_or_admin(
        current_user=current_user,
        target_user_id=user_id,
        db=db,
    )

    driver_profile = db.get(
        DriverProfile,
        user_id,
    )

    if driver_profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )

    return driver_profile


@router.patch(
    "/drivers/{user_id}/online-status",
    response_model=DriverProfileResponse,
)
def update_driver_online_status(
    user_id: UUID,
    payload: DriverOnlineStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles("driver")
    ),
):
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Drivers can only change their own online status.",
        )

    driver_profile = db.get(
        DriverProfile,
        user_id,
    )

    if driver_profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )

    if payload.is_online:
        if driver_profile.verification_status != "approved":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Driver must be approved before going online.",
            )

        approved_vehicle = db.scalar(
            select(Vehicle).where(
                Vehicle.driver_id == user_id,
                Vehicle.verification_status == "approved",
                Vehicle.is_active.is_(True),
            )
        )

        if approved_vehicle is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Driver must have an approved active vehicle "
                    "before going online."
                ),
            )

    driver_profile.is_online = payload.is_online

    db.commit()
    db.refresh(driver_profile)

    return driver_profile