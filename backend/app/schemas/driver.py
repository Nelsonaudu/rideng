from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.verification import VerificationStatus


class DriverProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    verification_status: VerificationStatus
    is_online: bool
    average_rating: Decimal | None
    rating_count: int
    total_rides: int
    created_at: datetime


class DriverOnlineStatusUpdate(BaseModel):
    is_online: bool