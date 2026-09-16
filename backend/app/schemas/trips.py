from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
)


class TripStateResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: UUID

    ride_request_id: UUID

    active_assignment_id: (
        UUID | None
    )

    rider_id: UUID

    status: str

    agreed_fare: Decimal
    payment_method: str

    matched_at: datetime

    driver_arriving_at: (
        datetime | None
    )

    arrived_at: (
        datetime | None
    )

    started_at: (
        datetime | None
    )

    completed_at: (
        datetime | None
    )