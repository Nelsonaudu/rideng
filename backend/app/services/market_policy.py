from dataclasses import dataclass
from datetime import date
from typing import Iterable, Protocol


class ComplianceDocument(Protocol):
    document_type: str
    verification_status: str
    expires_at: date | None


@dataclass(frozen=True)
class DocumentRequirement:
    key: str
    accepted_types: tuple[str, ...]


@dataclass(frozen=True)
class DocumentPolicyResult:
    valid: bool
    missing_or_invalid_requirements: list[str]


# RideNG Abuja MVP policy.
#
# These values are intentionally kept in application policy rather
# than database constraints so RideNG can change market requirements
# without destructive schema migrations.
#
# Additional commercial permits can be added following local
# legal/compliance review.
ABUJA_DRIVER_DOCUMENT_REQUIREMENTS = (
    DocumentRequirement(
        key="drivers_license",
        accepted_types=(
            "drivers_license",
        ),
    ),
    DocumentRequirement(
        key="government_identity",
        accepted_types=(
            "government_id",
            "national_id",
            "passport",
        ),
    ),
)


ABUJA_VEHICLE_DOCUMENT_REQUIREMENTS = (
    DocumentRequirement(
        key="vehicle_licence",
        accepted_types=(
            "vehicle_licence_certificate",
        ),
    ),
    DocumentRequirement(
        key="insurance",
        accepted_types=(
            "insurance",
        ),
    ),
    DocumentRequirement(
        key="roadworthiness",
        accepted_types=(
            "roadworthiness_certificate",
        ),
    ),
)


def normalize_document_type(
    document_type: str,
) -> str:
    return document_type.strip().lower()


def evaluate_document_requirements(
    *,
    documents: Iterable[ComplianceDocument],
    requirements: tuple[DocumentRequirement, ...],
    today: date | None = None,
) -> DocumentPolicyResult:
    if today is None:
        today = date.today()

    valid_document_types: set[str] = set()

    for document in documents:
        if document.verification_status != "approved":
            continue

        if (
            document.expires_at is not None
            and document.expires_at < today
        ):
            continue

        valid_document_types.add(
            normalize_document_type(
                document.document_type
            )
        )

    missing_or_invalid: list[str] = []

    for requirement in requirements:
        requirement_satisfied = any(
            document_type
            in valid_document_types
            for document_type
            in requirement.accepted_types
        )

        if not requirement_satisfied:
            missing_or_invalid.append(
                requirement.key
            )

    return DocumentPolicyResult(
        valid=not missing_or_invalid,
        missing_or_invalid_requirements=(
            missing_or_invalid
        ),
    )