from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VehicleDocument(Base):
    __tablename__ = "vehicle_documents"

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

    # Flexible because vehicle-document requirements
    # vary between cities, states, and countries.
    #
    # Abuja examples may include:
    # vehicle_licence_certificate
    # insurance
    # roadworthiness_certificate
    # hackney_permit
    # operating_permit
    # ownership_document
    # vehicle_authorization
    document_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    document_number: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    issuing_authority: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    issuing_country: Mapped[str | None] = mapped_column(
        String(2),
        nullable=True,
    )

    issued_at: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    expires_at: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )

    verification_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        index=True,
    )

    verified_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    file_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "verification_status IN "
            "('pending', 'approved', 'rejected', 'suspended')",
            name="ck_vehicle_documents_verification_status",
        ),
    )