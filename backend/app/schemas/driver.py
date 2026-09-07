from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class DriverProfileResponse(BaseModel):
    user_id: UUID
    verification_status: str
    is_online: bool
    average_rating: Decimal | None
    rating_count: int
    total_rides: int
    created_at: datetime


class DriverOnlineStatusUpdate(BaseModel):
    is_online: bool