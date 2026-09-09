from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import get_db
from app.models.driver_profile import DriverProfile
from app.models.rider_profile import RiderProfile
from app.models.user import User
from app.models.user_role import UserRole as UserRoleModel
from app.schemas.user import UserCreate, UserResponse


router = APIRouter()


def get_user_roles(
    db: Session,
    user_id: UUID,
):
    return db.scalars(
        select(UserRoleModel.role)
        .where(UserRoleModel.user_id == user_id)
        .order_by(UserRoleModel.role)
    ).all()


def build_user_response(
    db: Session,
    db_user: User,
) -> UserResponse:
    roles = get_user_roles(
        db=db,
        user_id=db_user.id,
    )

    return UserResponse(
        id=db_user.id,
        first_name=db_user.first_name,
        last_name=db_user.last_name,
        phone_number=db_user.phone_number,
        email=db_user.email,
        roles=roles,
        is_active=db_user.is_active,
        created_at=db_user.created_at,
    )


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
        password_hash=hash_password(user.password),
    )

    db.add(db_user)

    # Remove duplicate roles while preserving order.
    unique_roles = list(dict.fromkeys(user.roles))
    role_values = [role.value for role in unique_roles]

    try:
        # Insert user first so PostgreSQL/SQLAlchemy
        # generates the user's UUID.
        db.flush()

        # Store roles.
        for role_value in role_values:
            db.add(
                UserRoleModel(
                    user_id=db_user.id,
                    role=role_value,
                )
            )

        # Automatically create RiderProfile
        # when the rider role is present.
        if "rider" in role_values:
            db.add(
                RiderProfile(
                    user_id=db_user.id,
                )
            )

        # Automatically create DriverProfile
        # when the driver role is present.
        if "driver" in role_values:
            db.add(
                DriverProfile(
                    user_id=db_user.id,
                )
            )

        db.commit()
        db.refresh(db_user)

    except IntegrityError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A user with this phone number "
                "or email already exists."
            ),
        ) from exc

    return build_user_response(
        db=db,
        db_user=db_user,
    )


@router.get(
    "/users",
    response_model=list[UserResponse],
)
def list_users(
    db: Session = Depends(get_db),
):
    users = db.scalars(
        select(User)
        .order_by(User.created_at)
    ).all()

    return [
        build_user_response(
            db=db,
            db_user=db_user,
        )
        for db_user in users
    ]


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    responses={
        404: {
            "description": "User not found",
        }
    },
)
def get_user(
    user_id: UUID,
    db: Session = Depends(get_db),
):
    db_user = db.get(
        User,
        user_id,
    )

    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    return build_user_response(
        db=db,
        db_user=db_user,
    )