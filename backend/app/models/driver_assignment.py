from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DriverAssignment(Base):
    __tablename__ = "driver_assignments"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    ride_request_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "ride_requests.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    driver_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "driver_profiles.user_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    vehicle_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "vehicles.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    ride_offer_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "ride_offers.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="active",
        nullable=False,
        index=True,
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    pickup_eta_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            (
                "status IN ("
                "'active', "
                "'cancelled', "
                "'replaced', "
                "'completed'"
                ")"
            ),
            name="ck_driver_assignments_status",
        ),
        CheckConstraint(
            (
                "pickup_eta_seconds IS NULL "
                "OR pickup_eta_seconds >= 0"
            ),
            name="ck_driver_assignments_pickup_eta_nonnegative",
        ),
        Index(
            "uq_driver_assignments_active_request",
            "ride_request_id",
            unique=True,
            postgresql_where=text(
                "status = 'active'"
            ),
        ),
        Index(
            "uq_driver_assignments_active_driver",
            "driver_id",
            unique=True,
            postgresql_where=text(
                "status = 'active'"
            ),
        ),
    )