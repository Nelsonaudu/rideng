from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class TripPinVerifyRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    pin: str = Field(
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
    )


class TripPinIssueResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    trip_id: UUID
    assignment_id: UUID

    pin: str = Field(
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
    )

    expires_at: datetime


class TripPinVerificationResponse(
    BaseModel
):
    model_config = ConfigDict(
        extra="forbid"
    )

    verified: bool

    attempt_count: int
    attempts_remaining: int

    locked_until: datetime | None