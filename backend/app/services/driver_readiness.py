from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.driver_document import DriverDocument
from app.models.driver_profile import DriverProfile
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.market_policy import (
    ABUJA_DRIVER_DOCUMENT_REQUIREMENTS,
    evaluate_document_requirements,
)
from app.services.vehicle_readiness import (
    VehicleReadinessSnapshot,
    get_vehicle_readiness,
)


@dataclass
class DriverReadinessSnapshot:
    driver_id: UUID

    user_active: bool
    driver_compliance_approved: bool
    driver_documents_valid: bool

    eligible_vehicle_ids: list[UUID]

    online_eligible: bool

    missing_or_invalid_driver_requirements: list[str]
    blockers: list[str]


def calculate_driver_readiness(
    *,
    driver_profile: DriverProfile,
    user_active: bool,
    driver_documents: Iterable[DriverDocument],
    vehicle_readiness: Iterable[
        VehicleReadinessSnapshot
    ],
    now: datetime | None = None,
) -> DriverReadinessSnapshot:
    if now is None:
        now = datetime.now(UTC)

    document_policy = evaluate_document_requirements(
        documents=driver_documents,
        requirements=(
            ABUJA_DRIVER_DOCUMENT_REQUIREMENTS
        ),
        today=now.date(),
    )

    driver_profile_approved = (
        driver_profile.verification_status
        == "approved"
    )

    driver_compliance_approved = (
        user_active
        and driver_profile_approved
        and document_policy.valid
    )

    eligible_vehicle_ids = [
        readiness.vehicle_id
        for readiness in vehicle_readiness
        if readiness.ride_eligible
    ]

    blockers: list[str] = []

    if not user_active:
        blockers.append(
            "user_inactive"
        )

    if driver_profile.verification_status == "rejected":
        blockers.append(
            "driver_rejected"
        )

    elif driver_profile.verification_status == "suspended":
        blockers.append(
            "driver_suspended"
        )

    elif not driver_profile_approved:
        blockers.append(
            "driver_compliance_not_approved"
        )

    if not document_policy.valid:
        blockers.append(
            "driver_documents_missing_or_invalid"
        )

    if not eligible_vehicle_ids:
        blockers.append(
            "no_ride_eligible_vehicle"
        )

    online_eligible = (
        driver_compliance_approved
        and bool(eligible_vehicle_ids)
    )

    return DriverReadinessSnapshot(
        driver_id=driver_profile.user_id,
        user_active=user_active,
        driver_compliance_approved=(
            driver_compliance_approved
        ),
        driver_documents_valid=(
            document_policy.valid
        ),
        eligible_vehicle_ids=eligible_vehicle_ids,
        online_eligible=online_eligible,
        missing_or_invalid_driver_requirements=(
            document_policy
            .missing_or_invalid_requirements
        ),
        blockers=blockers,
    )


def get_driver_readiness(
    *,
    db: Session,
    driver_profile: DriverProfile,
) -> DriverReadinessSnapshot:
    user = db.get(
        User,
        driver_profile.user_id,
    )

    driver_documents = db.scalars(
        select(DriverDocument).where(
            DriverDocument.driver_id
            == driver_profile.user_id
        )
    ).all()

    vehicles = db.scalars(
        select(Vehicle).where(
            Vehicle.driver_id
            == driver_profile.user_id
        )
    ).all()

    vehicle_readiness = [
        get_vehicle_readiness(
            db=db,
            vehicle=vehicle,
        )
        for vehicle in vehicles
    ]

    return calculate_driver_readiness(
        driver_profile=driver_profile,
        user_active=(
            user is not None
            and bool(user.is_active)
        ),
        driver_documents=driver_documents,
        vehicle_readiness=vehicle_readiness,
    )