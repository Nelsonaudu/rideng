from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.vehicle import Vehicle
from app.models.vehicle_document import VehicleDocument
from app.models.vehicle_inspection import VehicleInspection
from app.services.market_policy import (
    ABUJA_VEHICLE_DOCUMENT_REQUIREMENTS,
    evaluate_document_requirements,
)


@dataclass
class VehicleReadinessSnapshot:
    vehicle_id: UUID

    inspection_required: bool
    inspection_eligible: bool
    inspection_valid: bool

    latest_inspection_status: str | None
    inspection_expires_at: datetime | None

    vehicle_compliance_approved: bool
    ride_eligible: bool

    missing_or_invalid_vehicle_requirements: list[str]
    blockers: list[str]


def calculate_vehicle_readiness(
    *,
    vehicle: Vehicle,
    latest_inspection: VehicleInspection | None,
    vehicle_documents: Iterable[VehicleDocument] | None = None,
    now: datetime | None = None,
) -> VehicleReadinessSnapshot:
    if now is None:
        now = datetime.now(UTC)

    latest_status = (
        latest_inspection.status
        if latest_inspection is not None
        else None
    )

    inspection_expires_at = (
        latest_inspection.expires_at
        if latest_inspection is not None
        else None
    )

    inspection_valid = False

    if (
        latest_inspection is not None
        and latest_status == "passed"
    ):
        inspection_valid = (
            inspection_expires_at is None
            or inspection_expires_at > now
        )

    inspection_required = not inspection_valid

    blocked_vehicle_statuses = {
        "rejected",
        "suspended",
    }

    inspection_eligible = (
        bool(vehicle.is_active)
        and vehicle.verification_status
        not in blocked_vehicle_statuses
    )

    # None preserves compatibility with pure/legacy unit tests.
    # Production database calculations always pass the actual
    # document collection, including an empty collection.
    if vehicle_documents is None:
        document_policy_valid = (
            vehicle.verification_status
            == "approved"
        )

        missing_vehicle_requirements: list[str] = []

    else:
        document_policy = (
            evaluate_document_requirements(
                documents=vehicle_documents,
                requirements=(
                    ABUJA_VEHICLE_DOCUMENT_REQUIREMENTS
                ),
                today=now.date(),
            )
        )

        document_policy_valid = (
            document_policy.valid
        )

        missing_vehicle_requirements = (
            document_policy
            .missing_or_invalid_requirements
        )

    vehicle_compliance_approved = (
        vehicle.verification_status == "approved"
        and document_policy_valid
    )

    blockers: list[str] = []

    if not vehicle.is_active:
        blockers.append(
            "vehicle_inactive"
        )

    if vehicle.verification_status == "rejected":
        blockers.append(
            "vehicle_rejected"
        )

    elif vehicle.verification_status == "suspended":
        blockers.append(
            "vehicle_suspended"
        )

    elif vehicle.verification_status != "approved":
        blockers.append(
            "vehicle_compliance_not_approved"
        )

    if not document_policy_valid:
        blockers.append(
            "vehicle_documents_missing_or_invalid"
        )

    if not inspection_valid:
        blockers.append(
            "valid_inspection_required"
        )

    ride_eligible = (
        bool(vehicle.is_active)
        and vehicle_compliance_approved
        and inspection_valid
    )

    return VehicleReadinessSnapshot(
        vehicle_id=vehicle.id,
        inspection_required=inspection_required,
        inspection_eligible=inspection_eligible,
        inspection_valid=inspection_valid,
        latest_inspection_status=latest_status,
        inspection_expires_at=inspection_expires_at,
        vehicle_compliance_approved=(
            vehicle_compliance_approved
        ),
        ride_eligible=ride_eligible,
        missing_or_invalid_vehicle_requirements=(
            missing_vehicle_requirements
        ),
        blockers=blockers,
    )


def get_vehicle_readiness(
    *,
    db: Session,
    vehicle: Vehicle,
) -> VehicleReadinessSnapshot:
    latest_inspection = db.scalar(
        select(VehicleInspection)
        .where(
            VehicleInspection.vehicle_id
            == vehicle.id
        )
        .order_by(
            VehicleInspection.created_at.desc()
        )
        .limit(1)
    )

    vehicle_documents = db.scalars(
        select(VehicleDocument).where(
            VehicleDocument.vehicle_id
            == vehicle.id
        )
    ).all()

    return calculate_vehicle_readiness(
        vehicle=vehicle,
        latest_inspection=latest_inspection,
        vehicle_documents=vehicle_documents,
    )