from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class PickupLocationRequest(
    BaseModel
):
    model_config = ConfigDict(
        extra="forbid",
    )

    sample_id: UUID

    latitude: Decimal = Field(
        ge=Decimal("-90"),
        le=Decimal("90"),
    )

    longitude: Decimal = Field(
        ge=Decimal("-180"),
        le=Decimal("180"),
    )

    horizontal_accuracy_m: Decimal = (
        Field(
            gt=Decimal("0"),
            le=Decimal("10000"),
        )
    )

    captured_at: datetime

    reported_speed_mps: (
        Decimal | None
    ) = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("200"),
    )

    is_mocked: bool | None = None


class PickupLocationResponse(
    BaseModel
):
    replayed: bool

    distance_to_pickup_m: float

    progress_verified: bool

    progress_newly_verified: bool

    arrival_candidate_count: int

    arrival_verified: bool

    arrival_newly_verified: bool