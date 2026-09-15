from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.verification import VerificationStatus


# ============================================================
# SHARED TYPES
# ============================================================


VehicleInspectionStatus = Literal[
    "pending_inspection",
    "passed",
    "failed",
    "reinspection_required",
    "cancelled",
]


# ============================================================
# DRIVER DOCUMENTS
# ============================================================


class DriverDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(
        min_length=2,
        max_length=100,
    )

    document_number: str | None = Field(
        default=None,
        max_length=150,
    )

    issuing_authority: str | None = Field(
        default=None,
        max_length=150,
    )

    issuing_country: str | None = Field(
        default=None,
        min_length=2,
        max_length=2,
    )

    issued_at: date | None = None
    expires_at: date | None = None

    file_url: str | None = Field(
        default=None,
        max_length=500,
    )


class DriverDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    driver_id: UUID

    document_type: str
    document_number: str | None
    issuing_authority: str | None
    issuing_country: str | None

    issued_at: date | None
    expires_at: date | None

    verification_status: VerificationStatus

    verified_by: UUID | None
    verified_at: datetime | None
    rejection_reason: str | None

    file_url: str | None
    created_at: datetime


# ============================================================
# VEHICLE DOCUMENTS
# ============================================================


class VehicleDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(
        min_length=2,
        max_length=100,
    )

    document_number: str | None = Field(
        default=None,
        max_length=150,
    )

    issuing_authority: str | None = Field(
        default=None,
        max_length=150,
    )

    issuing_country: str | None = Field(
        default=None,
        min_length=2,
        max_length=2,
    )

    issued_at: date | None = None
    expires_at: date | None = None

    file_url: str | None = Field(
        default=None,
        max_length=500,
    )


class VehicleDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vehicle_id: UUID

    document_type: str
    document_number: str | None
    issuing_authority: str | None
    issuing_country: str | None

    issued_at: date | None
    expires_at: date | None

    verification_status: VerificationStatus

    verified_by: UUID | None
    verified_at: datetime | None
    rejection_reason: str | None

    file_url: str | None
    created_at: datetime


# ============================================================
# DOCUMENT VERIFICATION
# ============================================================


class DocumentVerificationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_status: VerificationStatus

    rejection_reason: str | None = Field(
        default=None,
        max_length=1000,
    )


# ============================================================
# VEHICLE INSPECTIONS
# ============================================================


class VehicleInspectionCreate(BaseModel):
    """
    Creates a pending physical inspection record.

    Physical findings are deliberately excluded here because they
    belong to VehicleInspectionUpdate after an inspection actually
    takes place.
    """

    model_config = ConfigDict(extra="forbid")

    inspection_type: str = Field(
        default="initial",
        min_length=2,
        max_length=50,
    )

    inspection_location: str | None = Field(
        default=None,
        max_length=250,
    )

    inspection_provider: str | None = Field(
        default=None,
        max_length=150,
    )

    inspection_reference: str | None = Field(
        default=None,
        max_length=100,
    )

    notes: str | None = Field(
        default=None,
        max_length=2000,
    )


class VehicleInspectionUpdate(BaseModel):
    """
    Records or updates a physical inspection outcome.

    inspected_at and inspector_id remain server controlled.
    """

    model_config = ConfigDict(extra="forbid")

    status: VehicleInspectionStatus | None = None

    expires_at: datetime | None = None

    inspection_location: str | None = Field(
        default=None,
        max_length=250,
    )

    inspection_provider: str | None = Field(
        default=None,
        max_length=150,
    )

    inspection_reference: str | None = Field(
        default=None,
        max_length=100,
    )

    odometer_km: int | None = Field(
        default=None,
        ge=0,
    )

    checklist_data: dict[str, Any] | None = None
    evidence_data: dict[str, Any] | None = None

    failure_reason: str | None = Field(
        default=None,
        max_length=2000,
    )

    notes: str | None = Field(
        default=None,
        max_length=2000,
    )


class VehicleInspectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vehicle_id: UUID
    inspector_id: UUID | None

    inspection_type: str
    status: VehicleInspectionStatus

    inspected_at: datetime | None
    expires_at: datetime | None

    inspection_location: str | None
    inspection_provider: str | None
    inspection_reference: str | None

    odometer_km: int | None

    checklist_data: dict[str, Any] | None
    evidence_data: dict[str, Any] | None

    failure_reason: str | None
    notes: str | None

    created_at: datetime
    updated_at: datetime