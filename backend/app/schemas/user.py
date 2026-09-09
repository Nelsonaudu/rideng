from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    rider = "rider"
    driver = "driver"
    admin = "admin"


class PublicUserRole(str, Enum):
    rider = "rider"
    driver = "driver"


class UserCreate(BaseModel):
    first_name: str = Field(
        min_length=2,
        max_length=50,
    )

    last_name: str = Field(
        min_length=2,
        max_length=50,
    )

    phone_number: str = Field(
        min_length=10,
        max_length=20,
    )

    email: str | None = None

    password: str = Field(
        min_length=8,
        max_length=128,
    )

    roles: list[PublicUserRole] = Field(
        default_factory=lambda: [PublicUserRole.rider]
    )


class UserResponse(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    phone_number: str
    email: str | None
    roles: list[UserRole]
    is_active: bool
    created_at: datetime