from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_user_roles, require_roles
from app.db.session import get_db
from app.models.driver_document import DriverDocument
from app.models.driver_profile import DriverProfile
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_document import VehicleDocument
from app.models.vehicle_inspection import VehicleInspection
from app.schemas.compliance import (
    DocumentVerificationUpdate,
    DriverDocumentCreate,
    DriverDocumentResponse,
    VehicleDocumentCreate,
    VehicleDocumentResponse,
    VehicleInspectionCreate,
    VehicleInspectionResponse,
    VehicleInspectionUpdate,
)


router = APIRouter()


COMPLIANCE_STAFF_ROLES = {
    "admin",
    "compliance_agent",
}


# ============================================================
# HELPERS
# ============================================================


def ensure_driver_exists(
    db: Session,
    driver_id: UUID,
) -> DriverProfile:
    driver = db.get(
        DriverProfile,
        driver_id,
    )

    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )

    return driver


def ensure_vehicle_exists(
    db: Session,
    vehicle_id: UUID,
) -> Vehicle:
    vehicle = db.get(
        Vehicle,
        vehicle_id,
    )

    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found.",
        )

    return vehicle


def ensure_driver_compliance_access(
    db: Session,
    current_user: User,
    driver_id: UUID,
) -> None:
    if current_user.id == driver_id:
        return

    roles = get_user_roles(
        db=db,
        user_id=current_user.id,
    )

    if roles.intersection(COMPLIANCE_STAFF_ROLES):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You cannot access another driver's compliance records.",
    )


def ensure_vehicle_compliance_access(
    db: Session,
    current_user: User,
    vehicle: Vehicle,
) -> None:
    if vehicle.driver_id == current_user.id:
        return

    roles = get_user_roles(
        db=db,
        user_id=current_user.id,
    )

    if roles.intersection(COMPLIANCE_STAFF_ROLES):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You cannot access another driver's vehicle compliance records.",
    )


def validate_document_dates(
    issued_at,
    expires_at,
) -> None:
    if (
        issued_at is not None
        and expires_at is not None
        and expires_at < issued_at
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Document expiry date cannot be earlier than issue date.",
        )


def apply_document_verification(
    db,
    verification: DocumentVerificationUpdate,
    current_user: User,
    session: Session,
):
    new_status = verification.verification_status.value

    if (
        new_status == "rejected"
        and not verification.rejection_reason
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "A rejection reason is required when rejecting "
                "a document."
            ),
        )

    db.verification_status = new_status
    db.verified_by = current_user.id
    db.verified_at = datetime.now(UTC)

    if new_status == "rejected":
        db.rejection_reason = verification.rejection_reason
    else:
        db.rejection_reason = None

    session.commit()
    session.refresh(db)

    return db


# ============================================================
# DRIVER DOCUMENTS
# ============================================================


@router.post(
    "/api/v1/drivers/{driver_id}/documents",
    response_model=DriverDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Compliance"],
)
def create_driver_document(
    driver_id: UUID,
    document: DriverDocumentCreate,
    current_user: User = Depends(
        require_roles(
            "driver",
            "admin",
        )
    ),
    db: Session = Depends(get_db),
):
    ensure_driver_exists(
        db=db,
        driver_id=driver_id,
    )

    ensure_driver_compliance_access(
        db=db,
        current_user=current_user,
        driver_id=driver_id,
    )

    validate_document_dates(
        issued_at=document.issued_at,
        expires_at=document.expires_at,
    )

    db_document = DriverDocument(
        driver_id=driver_id,
        **document.model_dump(),
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)

    return db_document


@router.get(
    "/api/v1/drivers/{driver_id}/documents",
    response_model=list[DriverDocumentResponse],
    tags=["Compliance"],
)
def list_driver_documents(
    driver_id: UUID,
    current_user: User = Depends(
        require_roles(
            "driver",
            "admin",
            "compliance_agent",
        )
    ),
    db: Session = Depends(get_db),
):
    ensure_driver_exists(
        db=db,
        driver_id=driver_id,
    )

    ensure_driver_compliance_access(
        db=db,
        current_user=current_user,
        driver_id=driver_id,
    )

    documents = db.scalars(
        select(DriverDocument)
        .where(
            DriverDocument.driver_id == driver_id
        )
        .order_by(
            DriverDocument.created_at.desc()
        )
    ).all()

    return documents


# ============================================================
# VEHICLE DOCUMENTS
# ============================================================


@router.post(
    "/api/v1/vehicles/{vehicle_id}/documents",
    response_model=VehicleDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Compliance"],
)
def create_vehicle_document(
    vehicle_id: UUID,
    document: VehicleDocumentCreate,
    current_user: User = Depends(
        require_roles(
            "driver",
            "admin",
        )
    ),
    db: Session = Depends(get_db),
):
    vehicle = ensure_vehicle_exists(
        db=db,
        vehicle_id=vehicle_id,
    )

    ensure_vehicle_compliance_access(
        db=db,
        current_user=current_user,
        vehicle=vehicle,
    )

    validate_document_dates(
        issued_at=document.issued_at,
        expires_at=document.expires_at,
    )

    db_document = VehicleDocument(
        vehicle_id=vehicle_id,
        **document.model_dump(),
    )

    db.add(db_document)
    db.commit()
    db.refresh(db_document)

    return db_document


@router.get(
    "/api/v1/vehicles/{vehicle_id}/documents",
    response_model=list[VehicleDocumentResponse],
    tags=["Compliance"],
)
def list_vehicle_documents(
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
    vehicle = ensure_vehicle_exists(
        db=db,
        vehicle_id=vehicle_id,
    )

    ensure_vehicle_compliance_access(
        db=db,
        current_user=current_user,
        vehicle=vehicle,
    )

    documents = db.scalars(
        select(VehicleDocument)
        .where(
            VehicleDocument.vehicle_id == vehicle_id
        )
        .order_by(
            VehicleDocument.created_at.desc()
        )
    ).all()

    return documents


# ============================================================
# DRIVER DOCUMENT VERIFICATION
# ============================================================


@router.patch(
    "/api/v1/admin/driver-documents/{document_id}/verification",
    response_model=DriverDocumentResponse,
    include_in_schema=False,
)
@router.patch(
    "/api/v1/compliance/driver-documents/{document_id}/verification",
    response_model=DriverDocumentResponse,
    tags=["Compliance Staff"],
)
def verify_driver_document(
    document_id: UUID,
    verification: DocumentVerificationUpdate,
    current_user: User = Depends(
        require_roles(
            "admin",
            "compliance_agent",
        )
    ),
    db: Session = Depends(get_db),
):
    db_document = db.get(
        DriverDocument,
        document_id,
    )

    if db_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver document not found.",
        )

    return apply_document_verification(
        db=db_document,
        verification=verification,
        current_user=current_user,
        session=db,
    )


# ============================================================
# VEHICLE DOCUMENT VERIFICATION
# ============================================================


@router.patch(
    "/api/v1/admin/vehicle-documents/{document_id}/verification",
    response_model=VehicleDocumentResponse,
    include_in_schema=False,
)
@router.patch(
    "/api/v1/compliance/vehicle-documents/{document_id}/verification",
    response_model=VehicleDocumentResponse,
    tags=["Compliance Staff"],
)
def verify_vehicle_document(
    document_id: UUID,
    verification: DocumentVerificationUpdate,
    current_user: User = Depends(
        require_roles(
            "admin",
            "compliance_agent",
        )
    ),
    db: Session = Depends(get_db),
):
    db_document = db.get(
        VehicleDocument,
        document_id,
    )

    if db_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle document not found.",
        )

    return apply_document_verification(
        db=db_document,
        verification=verification,
        current_user=current_user,
        session=db,
    )


# ============================================================
# VEHICLE INSPECTIONS
# ============================================================


@router.post(
    "/api/v1/admin/vehicles/{vehicle_id}/inspections",
    response_model=VehicleInspectionResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/api/v1/compliance/vehicles/{vehicle_id}/inspections",
    response_model=VehicleInspectionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Compliance Staff"],
)
def create_vehicle_inspection(
    vehicle_id: UUID,
    inspection: VehicleInspectionCreate,
    current_user: User = Depends(
        require_roles(
            "admin",
            "compliance_agent",
        )
    ),
    db: Session = Depends(get_db),
):
    ensure_vehicle_exists(
        db=db,
        vehicle_id=vehicle_id,
    )

    existing_pending_inspection = db.scalar(
        select(VehicleInspection).where(
            VehicleInspection.vehicle_id == vehicle_id,
            VehicleInspection.status == "pending_inspection",
        )
    )

    if existing_pending_inspection is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This vehicle already has a pending inspection.",
        )

    db_inspection = VehicleInspection(
        vehicle_id=vehicle_id,
        inspector_id=None,
        status="pending_inspection",
        **inspection.model_dump(),
    )

    db.add(db_inspection)
    db.commit()
    db.refresh(db_inspection)

    return db_inspection


@router.get(
    "/api/v1/vehicles/{vehicle_id}/inspections",
    response_model=list[VehicleInspectionResponse],
    tags=["Compliance"],
)
def list_vehicle_inspections(
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
    vehicle = ensure_vehicle_exists(
        db=db,
        vehicle_id=vehicle_id,
    )

    ensure_vehicle_compliance_access(
        db=db,
        current_user=current_user,
        vehicle=vehicle,
    )

    inspections = db.scalars(
        select(VehicleInspection)
        .where(
            VehicleInspection.vehicle_id == vehicle_id
        )
        .order_by(
            VehicleInspection.created_at.desc()
        )
    ).all()

    return inspections


@router.patch(
    "/api/v1/admin/vehicle-inspections/{inspection_id}",
    response_model=VehicleInspectionResponse,
    include_in_schema=False,
)
@router.patch(
    "/api/v1/compliance/vehicle-inspections/{inspection_id}",
    response_model=VehicleInspectionResponse,
    tags=["Compliance Staff"],
)
def update_vehicle_inspection(
    inspection_id: UUID,
    inspection: VehicleInspectionUpdate,
    current_user: User = Depends(
        require_roles(
            "admin",
            "compliance_agent",
        )
    ),
    db: Session = Depends(get_db),
):
    db_inspection = db.get(
        VehicleInspection,
        inspection_id,
    )

    if db_inspection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle inspection not found.",
        )

    allowed_statuses = {
        "pending_inspection",
        "passed",
        "failed",
        "reinspection_required",
        "cancelled",
    }

    update_data = inspection.model_dump(
        exclude_unset=True
    )

    new_status = update_data.get("status")

    if (
        new_status is not None
        and new_status not in allowed_statuses
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid vehicle inspection status.",
        )

    if new_status in {
        "failed",
        "reinspection_required",
    }:
        new_failure_reason = update_data.get(
            "failure_reason"
        )

        if (
            not new_failure_reason
            and not db_inspection.failure_reason
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "A reason is required for a failed inspection "
                    "or when reinspection is required."
                ),
            )

    for field, value in update_data.items():
        setattr(
            db_inspection,
            field,
            value,
        )

    db_inspection.inspector_id = current_user.id
    db_inspection.updated_at = datetime.now(UTC)

    completed_outcomes = {
        "passed",
        "failed",
        "reinspection_required",
    }

    if (
        new_status in completed_outcomes
        and db_inspection.inspected_at is None
    ):
        db_inspection.inspected_at = datetime.now(UTC)

    if new_status == "passed":
        db_inspection.failure_reason = None

    db.commit()
    db.refresh(db_inspection)

    return db_inspection