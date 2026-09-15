from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    ensure_self_or_admin,
    get_current_user,
    get_user_roles,
    require_roles,
)
from app.db.session import get_db
from app.models.driver_profile import DriverProfile
from app.models.user import User
from app.schemas.driver import (
    DriverOnlineStatusUpdate,
    DriverProfileResponse,
    DriverReadinessResponse,
)
from app.services.driver_readiness import (
    get_driver_readiness,
)


router = APIRouter()


DRIVER_READINESS_STAFF_ROLES = {
    "admin",
    "compliance_agent",
}


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


@router.get(
    "/drivers/{user_id}/readiness",
    response_model=DriverReadinessResponse,
)
def get_driver_readiness_endpoint(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        roles = get_user_roles(
            db=db,
            user_id=current_user.id,
        )

        if not roles.intersection(
            DRIVER_READINESS_STAFF_ROLES
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You cannot access another driver's "
                    "readiness."
                ),
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

    readiness = get_driver_readiness(
        db=db,
        driver_profile=driver_profile,
    )

    return DriverReadinessResponse(
        driver_id=readiness.driver_id,
        user_active=readiness.user_active,
        driver_compliance_approved=(
            readiness.driver_compliance_approved
        ),
        driver_documents_valid=(
            readiness.driver_documents_valid
        ),
        eligible_vehicle_ids=(
            readiness.eligible_vehicle_ids
        ),
        online_eligible=readiness.online_eligible,
        missing_or_invalid_driver_requirements=(
            readiness
            .missing_or_invalid_driver_requirements
        ),
        blockers=readiness.blockers,
    )


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
            detail=(
                "Drivers can only change their own "
                "online status."
            ),
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
        readiness = get_driver_readiness(
            db=db,
            driver_profile=driver_profile,
        )

        if not readiness.online_eligible:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": (
                        "Driver is not currently eligible "
                        "to go online."
                    ),
                    "blockers": readiness.blockers,
                    "missing_or_invalid_driver_requirements": (
                        readiness
                        .missing_or_invalid_driver_requirements
                    ),
                },
            )

    driver_profile.is_online = payload.is_online

    db.commit()
    db.refresh(driver_profile)

    return driver_profile