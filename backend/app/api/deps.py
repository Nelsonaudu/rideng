from collections.abc import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.models.user_role import UserRole as UserRoleModel


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_v1_prefix}/auth/login"
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={
            "WWW-Authenticate": "Bearer",
        },
    )

    try:
        payload = decode_access_token(token)

        subject = payload.get("sub")

        if subject is None:
            raise credentials_exception

        user_id = UUID(subject)

    except (
        InvalidTokenError,
        ValueError,
        TypeError,
    ) as exc:
        raise credentials_exception from exc

    user = db.get(
        User,
        user_id,
    )

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user.",
        )

    return user


def get_user_roles(
    db: Session,
    user_id: UUID,
) -> set[str]:
    roles = db.scalars(
        select(UserRoleModel.role).where(
            UserRoleModel.user_id == user_id
        )
    ).all()

    return set(roles)


def require_roles(
    *allowed_roles: str,
) -> Callable:
    def role_dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        user_roles = get_user_roles(
            db=db,
            user_id=current_user.id,
        )

        if not user_roles.intersection(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )

        return current_user

    return role_dependency


def ensure_self_or_admin(
    current_user: User,
    target_user_id: UUID,
    db: Session,
) -> None:
    if current_user.id == target_user_id:
        return

    roles = get_user_roles(
        db=db,
        user_id=current_user.id,
    )

    if "admin" in roles:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You cannot access another user's protected resource.",
    )