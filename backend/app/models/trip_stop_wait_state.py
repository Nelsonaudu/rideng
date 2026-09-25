from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TripStopWaitState(Base):
    __tablename__ = "trip_stop_wait_states"

    stop_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "trip_stops.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    trip_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "trips.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    assignment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "driver_assignments.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    free_wait_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    wait_rate_per_minute: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    driver_exit_right_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    extension_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    arrived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    free_wait_ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    driver_exit_right_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    current_paid_window_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    authorized_until: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    accrued_billable_seconds: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    extension_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    final_billable_seconds: Mapped[
        int | None
    ] = mapped_column(
        Integer,
        nullable=True,
    )

    final_wait_charge: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    closed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    close_reason: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "free_wait_seconds >= 0",
            name=(
                "ck_trip_stop_wait_"
                "free_wait_nonnegative"
            ),
        ),
        CheckConstraint(
            "driver_exit_right_seconds >= 0",
            name=(
                "ck_trip_stop_wait_"
                "exit_right_nonnegative"
            ),
        ),
        CheckConstraint(
            "extension_seconds > 0",
            name=(
                "ck_trip_stop_wait_"
                "extension_positive"
            ),
        ),
        CheckConstraint(
            "accrued_billable_seconds >= 0",
            name=(
                "ck_trip_stop_wait_"
                "accrued_nonnegative"
            ),
        ),
        CheckConstraint(
            "extension_count >= 0",
            name=(
                "ck_trip_stop_wait_"
                "extension_count_nonnegative"
            ),
        ),
        CheckConstraint(
            "wait_rate_per_minute >= 0",
            name=(
                "ck_trip_stop_wait_"
                "rate_nonnegative"
            ),
        ),
        CheckConstraint(
            (
                "final_billable_seconds "
                "IS NULL OR "
                "final_billable_seconds >= 0"
            ),
            name=(
                "ck_trip_stop_wait_"
                "final_seconds_nonnegative"
            ),
        ),
        CheckConstraint(
            (
                "final_wait_charge "
                "IS NULL OR "
                "final_wait_charge >= 0"
            ),
            name=(
                "ck_trip_stop_wait_"
                "final_charge_nonnegative"
            ),
        ),
        CheckConstraint(
            (
                "("
                "current_paid_window_started_at IS NULL "
                "AND authorized_until IS NULL"
                ") OR ("
                "current_paid_window_started_at IS NOT NULL "
                "AND authorized_until IS NOT NULL "
                "AND authorized_until >= "
                "current_paid_window_started_at"
                ")"
            ),
            name=(
                "ck_trip_stop_wait_"
                "authorized_window"
            ),
        ),
        CheckConstraint(
            (
                "closed_at IS NULL OR ("
                "current_paid_window_started_at IS NULL "
                "AND authorized_until IS NULL"
                ")"
            ),
            name=(
                "ck_trip_stop_wait_"
                "closed_window"
            ),
        ),
    )
