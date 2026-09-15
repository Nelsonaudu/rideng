from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.verification import VerificationStatus


class DriverProfileResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    user_id: UUID
    verification_status: VerificationStatus
    is_online: bool
    average_rating: Decimal | None
    rating_count: int
    total_rides: int
    created_at: datetime


class DriverOnlineStatusUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    is_online: bool


class DriverReadinessResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    driver_id: UUID

    user_active: bool
    driver_compliance_approved: bool
    driver_documents_valid: bool

    eligible_vehicle_ids: list[UUID]

    online_eligible: bool

    missing_or_invalid_driver_requirements: list[str]
    blockers: list[str]