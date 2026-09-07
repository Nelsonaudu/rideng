from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VehicleCreate(BaseModel):
    make: str = Field(min_length=2, max_length=50)
    model: str = Field(min_length=1, max_length=50)
    year: int = Field(ge=1980, le=2100)
    color: str = Field(min_length=2, max_length=30)
    plate_number: str = Field(min_length=3, max_length=20)

    @field_validator("plate_number")
    @classmethod
    def normalize_plate_number(cls, value: str) -> str:
        return value.strip().upper()


class VehicleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    driver_id: UUID
    make: str
    model: str
    year: int
    color: str
    plate_number: str
    verification_status: str
    is_active: bool
    created_at: datetime