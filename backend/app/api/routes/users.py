from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, status

from app.schemas.user import UserCreate, UserResponse


router = APIRouter()


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(user: UserCreate):
    return UserResponse(
        id=uuid4(),
        first_name=user.first_name,
        last_name=user.last_name,
        phone_number=user.phone_number,
        email=user.email,
        roles=user.roles,
        is_active=True,
        created_at=datetime.now(UTC),
    )