from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class VehicleReadinessResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

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