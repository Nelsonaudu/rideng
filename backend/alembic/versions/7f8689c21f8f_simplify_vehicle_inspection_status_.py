"""simplify vehicle inspection status workflow

Revision ID: 7f8689c21f8f
Revises: 422e7ceedade
Create Date: 2026-09-15

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7f8689c21f8f"
down_revision: Union[str, Sequence[str], None] = "422e7ceedade"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Replace the old operational inspection workflow:

        scheduled
        in_progress
        passed
        failed
        reinspection_required
        cancelled

    with the simplified compliance workflow:

        pending_inspection
        passed
        failed
        reinspection_required
        cancelled

    Legacy scheduled/in_progress records are safely converted to
    pending_inspection before the new constraint is installed.
    """

    # The existing constraint does not allow "pending_inspection",
    # so it must be removed before converting legacy rows.
    op.drop_constraint(
        "ck_vehicle_inspections_status",
        "vehicle_inspections",
        type_="check",
    )

    # Defensive migration:
    # another environment may already contain records using the
    # previous workflow even though our development database does not.
    op.execute(
        sa.text(
            """
            UPDATE vehicle_inspections
            SET status = 'pending_inspection'
            WHERE status IN ('scheduled', 'in_progress')
            """
        )
    )

    op.create_check_constraint(
        "ck_vehicle_inspections_status",
        "vehicle_inspections",
        """
        status IN (
            'pending_inspection',
            'passed',
            'failed',
            'reinspection_required',
            'cancelled'
        )
        """,
    )


def downgrade() -> None:
    """
    Restore the previous inspection status workflow.

    pending_inspection is converted back to scheduled because the
    previous database constraint did not recognize pending_inspection.
    """

    op.drop_constraint(
        "ck_vehicle_inspections_status",
        "vehicle_inspections",
        type_="check",
    )

    op.execute(
        sa.text(
            """
            UPDATE vehicle_inspections
            SET status = 'scheduled'
            WHERE status = 'pending_inspection'
            """
        )
    )

    op.create_check_constraint(
        "ck_vehicle_inspections_status",
        "vehicle_inspections",
        """
        status IN (
            'scheduled',
            'in_progress',
            'passed',
            'failed',
            'reinspection_required',
            'cancelled'
        )
        """,
    )