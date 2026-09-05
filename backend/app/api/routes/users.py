from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.user_role import UserRole as UserRoleModel
from app.schemas.user import UserCreate, UserResponse


router = APIRouter()


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
):
    db_user = User(
        first_name=user.first_name,
        last_name=user.last_name,
        phone_number=user.phone_number,
        email=user.email,
    )

    db.add(db_user)

    unique_roles = list(dict.fromkeys(user.roles))

    try:
        db.flush()

        for role in unique_roles:
            db.add(
                UserRoleModel(
                    user_id=db_user.id,
                    role=role.value,
                )
            )

        db.commit()
        db.refresh(db_user)

    except IntegrityError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this phone number or email already exists.",
        ) from exc

    return UserResponse(
        id=db_user.id,
        first_name=db_user.first_name,
        last_name=db_user.last_name,
        phone_number=db_user.phone_number,
        email=db_user.email,
        roles=unique_roles,
        is_active=db_user.is_active,
        created_at=db_user.created_at,
    )