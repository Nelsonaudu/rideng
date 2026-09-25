from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class TripStopLocationRequest(
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

    horizontal_accuracy_m: Decimal = Field(
        gt=Decimal("0"),
        le=Decimal("10000"),
    )

    captured_at: datetime

    reported_speed_mps: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("200"),
    )

    is_mocked: bool | None = None


class TripStopLocationResponse(
    BaseModel
):
    replayed: bool

    stop_id: UUID
    stop_sequence: int

    distance_to_stop_m: float

    arrival_candidate_count: int

    arrival_verified: bool
    arrival_newly_verified: bool


class TripStopWaitClosureResponse(
    BaseModel
):
    stop_id: UUID

    final_billable_seconds: int

    final_wait_charge: Decimal

    closed_at: datetime

    close_reason: str


class TripStopWaitExtensionResponse(
    BaseModel
):
    stop_id: UUID

    extension_number: int

    billable_seconds: int

    gross_wait_charge: Decimal

    authorized_until: datetime
