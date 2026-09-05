from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
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

    # Prevent duplicate roles such as ["rider", "rider"].
    unique_roles = list(dict.fromkeys(user.roles))

    try:
        # Create the user row and generate its UUID
        # without committing the transaction yet.
        db.flush()

        # Store each role in user_roles.
        for role in unique_roles:
            db.add(
                UserRoleModel(
                    user_id=db_user.id,
                    role=role.value,
                )
            )

        # Permanently save the user and roles.
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


@router.get(
    "/users",
    response_model=list[UserResponse],
)
def list_users(
    db: Session = Depends(get_db),
):
    users = db.scalars(
        select(User).order_by(User.created_at)
    ).all()

    results = []

    for db_user in users:
        roles = get_user_roles(
            db=db,
            user_id=db_user.id,
        )

        results.append(
            UserResponse(
                id=db_user.id,
                first_name=db_user.first_name,
                last_name=db_user.last_name,
                phone_number=db_user.phone_number,
                email=db_user.email,
                roles=roles,
                is_active=db_user.is_active,
                created_at=db_user.created_at,
            )
        )

    return results


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

    roles = get_user_roles(
        db=db,
        user_id=user_id,
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