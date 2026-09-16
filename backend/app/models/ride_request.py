from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RideRequest(Base):
    __tablename__ = "ride_requests"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    rider_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "rider_profiles.user_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    ride_mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="requested",
        nullable=False,
        index=True,
    )

    payment_method: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    pickup_address: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    pickup_latitude: Mapped[Decimal] = mapped_column(
        Numeric(10, 7),
        nullable=False,
    )

    pickup_longitude: Mapped[Decimal] = mapped_column(
        Numeric(10, 7),
        nullable=False,
    )

    destination_address: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    destination_latitude: Mapped[Decimal] = mapped_column(
        Numeric(10, 7),
        nullable=False,
    )

    destination_longitude: Mapped[Decimal] = mapped_column(
        Numeric(10, 7),
        nullable=False,
    )

    recommended_fare: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    minimum_offer_fare: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    quick_ride_fare: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    maximum_counteroffer_fare: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    rider_offer_fare: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    matched_fare: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
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

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "ride_mode IN ('quick_ride', 'negotiate')",
            name="ck_ride_requests_ride_mode",
        ),
        CheckConstraint(
            (
                "status IN ("
                "'requested', "
                "'searching', "
                "'matched', "
                "'rider_cancelled', "
                "'no_driver_found', "
                "'expired'"
                ")"
            ),
            name="ck_ride_requests_status",
        ),
        CheckConstraint(
            "payment_method IN ('cash', 'electronic')",
            name="ck_ride_requests_payment_method",
        ),
        CheckConstraint(
            "recommended_fare > 0",
            name="ck_ride_requests_recommended_fare_positive",
        ),
        CheckConstraint(
            "minimum_offer_fare > 0",
            name="ck_ride_requests_minimum_offer_positive",
        ),
        CheckConstraint(
            "quick_ride_fare > 0",
            name="ck_ride_requests_quick_fare_positive",
        ),
        CheckConstraint(
            "maximum_counteroffer_fare > 0",
            name="ck_ride_requests_max_counter_positive",
        ),
    )