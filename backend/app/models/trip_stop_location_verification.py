from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TripStopLocationVerificationState(Base):
    __tablename__ = (
        "trip_stop_location_verification_states"
    )

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

    last_sample_id: Mapped[
        UUID | None
    ] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )

    last_latitude: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(10, 7),
        nullable=True,
    )

    last_longitude: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(10, 7),
        nullable=True,
    )

    last_horizontal_accuracy_m: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(8, 2),
        nullable=True,
    )

    last_distance_to_stop_m: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    last_sample_captured_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_sample_received_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    arrival_candidate_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_arrival_candidate_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    arrival_verified_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
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
            "arrival_candidate_count >= 0",
            name=(
                "ck_trip_stop_location_"
                "arrival_candidate_count"
            ),
        ),
        CheckConstraint(
            (
                "last_horizontal_accuracy_m "
                "IS NULL OR "
                "last_horizontal_accuracy_m > 0"
            ),
            name=(
                "ck_trip_stop_location_"
                "accuracy_positive"
            ),
        ),
        CheckConstraint(
            (
                "last_distance_to_stop_m "
                "IS NULL OR "
                "last_distance_to_stop_m >= 0"
            ),
            name=(
                "ck_trip_stop_location_"
                "distance_nonnegative"
            ),
        ),
    )
