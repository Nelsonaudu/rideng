"""add compliance agent role

Revision ID: 9b7c4e2d1a6f
Revises: 7f8689c21f8f
Create Date: 2026-09-16

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9b7c4e2d1a6f"
down_revision: Union[str, Sequence[str], None] = "7f8689c21f8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow the least-privilege RideNG compliance staff role."""

    op.drop_constraint(
        "ck_user_roles_role",
        "user_roles",
        type_="check",
    )

    op.create_check_constraint(
        "ck_user_roles_role",
        "user_roles",
        "role IN ('rider', 'driver', 'admin', 'compliance_agent')",
    )


def downgrade() -> None:
    """Restore the previous RideNG role constraint."""

    # The old constraint cannot be restored while compliance-agent
    # assignments still exist.
    op.execute(
        "DELETE FROM user_roles "
        "WHERE role = 'compliance_agent'"
    )

    op.drop_constraint(
        "ck_user_roles_role",
        "user_roles",
        type_="check",
    )

    op.create_check_constraint(
        "ck_user_roles_role",
        "user_roles",
        "role IN ('rider', 'driver', 'admin')",
    )