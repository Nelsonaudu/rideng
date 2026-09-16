from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class DriverCancellationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    reason: str = Field(
        min_length=2,
        max_length=200,
    )


class RiderCancellationResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    ride_request_id: UUID
    trip_id: UUID | None

    ride_request_status: str
    trip_status: str | None

    cancellation_fee_eligible: bool


class DriverCancellationResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    ride_request_id: UUID
    trip_id: UUID
    assignment_id: UUID

    ride_request_status: str
    rematching: bool


class RiderNoShowResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    ride_request_id: UUID
    trip_id: UUID

    trip_status: str

    driver_compensation_eligible: bool