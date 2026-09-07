from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.driver_profile import DriverProfile
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
):
    driver_profile = db.get(DriverProfile, user_id)

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
):
    driver_profile = db.get(DriverProfile, user_id)

    if driver_profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )

    if payload.is_online and driver_profile.verification_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Driver must be approved before going online.",
        )

    driver_profile.is_online = payload.is_online

    db.commit()
    db.refresh(driver_profile)

    return driver_profile