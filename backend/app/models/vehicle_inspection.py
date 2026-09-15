from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VehicleInspection(Base):
    __tablename__ = "vehicle_inspections"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    vehicle_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "vehicles.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # Admin/compliance reviewer/inspection officer responsible
    # for recording the inspection result.
    inspector_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    # Flexible inspection type so markets can introduce
    # additional inspection workflows without a DB migration.
    #
    # Examples:
    # initial
    # periodic
    # reinspection
    # spot_check
    inspection_type: Mapped[str] = mapped_column(
        String(50),
        default="initial",
        nullable=False,
        index=True,
    )

    # Compliance state only.
    #
    # We deliberately do not include operational states such as
    # "checked_in" or "in_progress" here.
    #
    # pending_inspection
    # passed
    # failed
    # reinspection_required
    # cancelled
    status: Mapped[str] = mapped_column(
        String(30),
        default="pending_inspection",
        nullable=False,
        index=True,
    )

    # Time the physical inspection was actually performed /
    # completed. Remains NULL while inspection is pending.
    inspected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    # Date/time after which a passed inspection is no longer
    # considered valid.
    #
    # The validity period will eventually come from the market
    # compliance policy rather than being hard-coded here.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    inspection_location: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    inspection_provider: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    inspection_reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    odometer_km: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Flexible physical-inspection checklist.
    #
    # Example:
    #
    # {
    #     "brakes": {"passed": true},
    #     "tyres": {"passed": true},
    #     "lights": {"passed": true},
    #     "seatbelts": {"passed": true},
    #     "air_conditioning": {"passed": true},
    #     "windscreen": {"passed": true},
    #     "mirrors": {"passed": true},
    #     "interior_condition": {"passed": true},
    #     "exterior_condition": {"passed": true},
    #     "cleanliness": {"passed": true},
    #     "fire_extinguisher": {"passed": true},
    #     "warning_triangle": {"passed": true}
    # }
    checklist_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    # References to inspection evidence such as photographs
    # or an inspection report.
    #
    # Example:
    #
    # {
    #     "front_photo": "...",
    #     "rear_photo": "...",
    #     "interior_photo": "...",
    #     "inspection_report": "..."
    # }
    evidence_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
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
            "status IN "
            "('pending_inspection', "
            "'passed', "
            "'failed', "
            "'reinspection_required', "
            "'cancelled')",
            name="ck_vehicle_inspections_status",
        ),
        CheckConstraint(
            "odometer_km IS NULL OR odometer_km >= 0",
            name="ck_vehicle_inspections_odometer_nonnegative",
        ),
    )