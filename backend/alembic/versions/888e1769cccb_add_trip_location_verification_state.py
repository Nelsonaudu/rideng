"""add trip location verification state

Revision ID: 888e1769cccb
Revises: c41d2e7f9a30
Create Date: 2026-09-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "888e1769cccb"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "c41d2e7f9a30"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "trip_location_verification_states",

        sa.Column(
            "trip_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "assignment_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "last_sample_id",
            sa.UUID(),
            nullable=True,
        ),

        sa.Column(
            "last_latitude",
            sa.Numeric(
                precision=10,
                scale=7,
            ),
            nullable=True,
        ),

        sa.Column(
            "last_longitude",
            sa.Numeric(
                precision=10,
                scale=7,
            ),
            nullable=True,
        ),

        sa.Column(
            "last_horizontal_accuracy_m",
            sa.Numeric(
                precision=8,
                scale=2,
            ),
            nullable=True,
        ),

        sa.Column(
            "last_distance_to_pickup_m",
            sa.Numeric(
                precision=12,
                scale=2,
            ),
            nullable=True,
        ),

        sa.Column(
            "last_sample_captured_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.Column(
            "last_sample_received_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.Column(
            "progress_anchor_distance_to_pickup_m",
            sa.Numeric(
                precision=12,
                scale=2,
            ),
            nullable=True,
        ),

        sa.Column(
            "progress_anchor_horizontal_accuracy_m",
            sa.Numeric(
                precision=8,
                scale=2,
            ),
            nullable=True,
        ),

        sa.Column(
            "progress_anchor_captured_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.Column(
            "arrival_candidate_count",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "last_arrival_candidate_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.Column(
            "progress_verified_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.Column(
            "arrival_verified_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=False,
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=False,
        ),

        sa.CheckConstraint(
            (
                "arrival_candidate_count "
                ">= 0"
            ),
            name=(
                "ck_trip_location_"
                "arrival_candidate_count"
            ),
        ),

        sa.CheckConstraint(
            (
                "last_horizontal_accuracy_m "
                "IS NULL OR "
                "last_horizontal_accuracy_m "
                "> 0"
            ),
            name=(
                "ck_trip_location_"
                "accuracy_positive"
            ),
        ),

        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["driver_assignments.id"],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["trip_id"],
            ["trips.id"],
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint(
            "trip_id"
        ),
    )

    op.create_index(
        op.f(
            "ix_trip_location_verification_states_"
            "assignment_id"
        ),
        "trip_location_verification_states",
        ["assignment_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(
        op.f(
            "ix_trip_location_verification_states_"
            "assignment_id"
        ),
        table_name=(
            "trip_location_verification_states"
        ),
    )

    op.drop_table(
        "trip_location_verification_states"
    )