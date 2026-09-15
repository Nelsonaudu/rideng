from getpass import getpass

from pwdlib import PasswordHash
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.models.user import User
from app.models.user_role import UserRole as UserRoleModel


password_hash = PasswordHash.recommended()


def create_admin() -> None:
    print("\n=== RideNG Admin Bootstrap ===\n")

    first_name = input("First name: ").strip()
    last_name = input("Last name: ").strip()
    phone_number = input("Phone number: ").strip()
    email = input("Email: ").strip().lower()

    password = getpass("Password: ")
    password_confirmation = getpass("Confirm password: ")

    if not first_name:
        print("ERROR: First name is required.")
        return

    if not last_name:
        print("ERROR: Last name is required.")
        return

    if not phone_number:
        print("ERROR: Phone number is required.")
        return

    if not email:
        print("ERROR: Email is required.")
        return

    if len(password) < 8:
        print("ERROR: Password must contain at least 8 characters.")
        return

    if password != password_confirmation:
        print("ERROR: Passwords do not match.")
        return

    db = SessionLocal()

    try:
        existing_user = db.scalar(
            select(User).where(
                or_(
                    User.email == email,
                    User.phone_number == phone_number,
                )
            )
        )

        if existing_user is not None:
            print(
                "ERROR: A user with this email address "
                "or phone number already exists."
            )
            return

        admin_user = User(
            first_name=first_name,
            last_name=last_name,
            phone_number=phone_number,
            email=email,
            password_hash=password_hash.hash(password),
            is_active=True,
        )

        db.add(admin_user)

        # Generate the user's UUID before creating the role.
        db.flush()

        admin_role = UserRoleModel(
            user_id=admin_user.id,
            role="admin",
        )

        db.add(admin_role)
        db.commit()
        db.refresh(admin_user)

        print("\nAdmin account created successfully.")
        print(f"User ID: {admin_user.id}")
        print(f"Name: {admin_user.first_name} {admin_user.last_name}")
        print(f"Email: {admin_user.email}")
        print("Role: admin")
        print("\nYou can now log in through /api/v1/auth/login.")

    except SQLAlchemyError as exc:
        db.rollback()
        print("\nERROR: Admin account could not be created.")
        print(f"Database error: {exc}")

    finally:
        db.close()


if __name__ == "__main__":
    create_admin()