from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.driver_profile import DriverProfile
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehicleResponse


router = APIRouter()


@router.post(
    "/drivers/{driver_id}/vehicles",
    response_model=VehicleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_vehicle(
    driver_id: UUID,
    vehicle: VehicleCreate,
    db: Session = Depends(get_db),
):
    driver_profile = db.get(
        DriverProfile,
        driver_id,
    )

    if driver_profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not registered as a driver.",
        )

    db_vehicle = Vehicle(
        driver_id=driver_id,
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        color=vehicle.color,
        plate_number=vehicle.plate_number,
    )

    db.add(db_vehicle)

    try:
        db.commit()
        db.refresh(db_vehicle)

    except IntegrityError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A vehicle with this plate number already exists.",
        ) from exc

    return db_vehicle


@router.get(
    "/drivers/{driver_id}/vehicles",
    response_model=list[VehicleResponse],
)
def list_driver_vehicles(
    driver_id: UUID,
    db: Session = Depends(get_db),
):
    driver_profile = db.get(
        DriverProfile,
        driver_id,
    )

    if driver_profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )

    vehicles = db.scalars(
        select(Vehicle)
        .where(Vehicle.driver_id == driver_id)
        .order_by(Vehicle.created_at)
    ).all()

    return vehicles