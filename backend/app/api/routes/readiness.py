from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_user_roles, require_roles
from app.db.session import get_db
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.readiness import VehicleReadinessResponse
from app.services.vehicle_readiness import get_vehicle_readiness


router = APIRouter()


STAFF_ROLES = {
    "admin",
    "compliance_agent",
}


@router.get(
    "/api/v1/vehicles/{vehicle_id}/readiness",
    response_model=VehicleReadinessResponse,
    tags=["Compliance"],
)
def read_vehicle_readiness(
    vehicle_id: UUID,
    current_user: User = Depends(
        require_roles(
            "driver",
            "admin",
            "compliance_agent",
        )
    ),
    db: Session = Depends(get_db),
):
    vehicle = db.get(
        Vehicle,
        vehicle_id,
    )

    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found.",
        )

    if vehicle.driver_id != current_user.id:
        roles = get_user_roles(
            db=db,
            user_id=current_user.id,
        )

        if not roles.intersection(
            STAFF_ROLES
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You cannot access another driver's "
                    "vehicle readiness."
                ),
            )

    snapshot = get_vehicle_readiness(
        db=db,
        vehicle=vehicle,
    )

    return VehicleReadinessResponse(
        vehicle_id=snapshot.vehicle_id,
        inspection_required=snapshot.inspection_required,
        inspection_eligible=snapshot.inspection_eligible,
        inspection_valid=snapshot.inspection_valid,
        latest_inspection_status=(
            snapshot.latest_inspection_status
        ),
        inspection_expires_at=(
            snapshot.inspection_expires_at
        ),
        vehicle_compliance_approved=(
            snapshot.vehicle_compliance_approved
        ),
        ride_eligible=snapshot.ride_eligible,
        blockers=snapshot.blockers,
    )