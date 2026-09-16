from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from uuid import UUID

from app.models.driver_assignment import (
    DriverAssignment,
)
from app.models.trip import Trip
from app.models.trip_start_verification import (
    TripStartVerification,
)


@dataclass(frozen=True)
class TripPinPolicy:
    max_attempts: int
    lock_seconds: int
    ttl_seconds: int


@dataclass(frozen=True)
class TripPinIssueResult:
    verification: TripStartVerification
    pin: str


@dataclass(frozen=True)
class TripPinCheckResult:
    verified: bool
    attempt_count: int
    attempts_remaining: int
    locked_until: datetime | None


ABUJA_TRIP_PIN_POLICY = TripPinPolicy(
    max_attempts=3,
    lock_seconds=60,
    ttl_seconds=21600,
)


class TripVerificationError(
    ValueError
):
    pass


class TripPinFormatError(
    TripVerificationError
):
    pass


class TripPinStateError(
    TripVerificationError
):
    pass


class TripPinLockedError(
    TripVerificationError
):
    pass


class TripPinExpiredError(
    TripVerificationError
):
    pass


class TripPinInvalidatedError(
    TripVerificationError
):
    pass


class TripPinAlreadyVerifiedError(
    TripVerificationError
):
    pass


class TripStartAuthorizationError(
    TripVerificationError
):
    pass


def _resolve_secret(
    secret: str | None,
) -> str:
    if secret:
        return secret

    from app.core.config import settings

    return settings.jwt_secret_key


def _validate_pin_format(
    pin: str,
) -> None:
    if (
        len(pin) != 4
        or not pin.isdigit()
    ):
        raise TripPinFormatError(
            "Trip PIN must contain "
            "exactly four digits."
        )


def generate_trip_pin() -> str:
    return (
        f"{secrets.randbelow(10000):04d}"
    )


def hash_trip_pin(
    *,
    pin: str,
    assignment_id: UUID,
    secret: str | None = None,
) -> str:
    _validate_pin_format(
        pin
    )

    resolved_secret = (
        _resolve_secret(
            secret
        )
    )

    message = (
        "rideng-trip-start-pin-v1:"
        f"{assignment_id}:"
        f"{pin}"
    ).encode(
        "utf-8"
    )

    return hmac.new(
        resolved_secret.encode(
            "utf-8"
        ),
        message,
        hashlib.sha256,
    ).hexdigest()


def trip_pin_matches(
    *,
    pin: str,
    pin_hash: str,
    assignment_id: UUID,
    secret: str | None = None,
) -> bool:
    try:
        candidate_hash = (
            hash_trip_pin(
                pin=pin,
                assignment_id=(
                    assignment_id
                ),
                secret=secret,
            )
        )

    except TripPinFormatError:
        return False

    return hmac.compare_digest(
        candidate_hash,
        pin_hash,
    )


def _validate_trip_assignment(
    *,
    trip: Trip,
    assignment: DriverAssignment,
) -> None:
    if (
        trip.active_assignment_id
        != assignment.id
    ):
        raise TripPinStateError(
            "Verification assignment is "
            "not the trip's active assignment."
        )

    if (
        assignment.ride_request_id
        != trip.ride_request_id
    ):
        raise TripPinStateError(
            "Assignment does not belong "
            "to this trip."
        )

    if (
        assignment.status
        != "active"
    ):
        raise TripPinStateError(
            "Driver assignment is not active."
        )


def issue_trip_start_pin(
    *,
    trip: Trip,
    assignment: DriverAssignment,
    existing_verification: (
        TripStartVerification | None
    ),
    now: datetime | None = None,
    secret: str | None = None,
    policy: TripPinPolicy = (
        ABUJA_TRIP_PIN_POLICY
    ),
) -> TripPinIssueResult:
    now = (
        now
        or datetime.now(UTC)
    )

    _validate_trip_assignment(
        trip=trip,
        assignment=assignment,
    )

    if trip.status not in {
        "matched",
        "driver_arriving",
        "driver_arrived",
    }:
        raise TripPinStateError(
            "Trip PIN cannot be issued "
            "in the current trip state."
        )

    if (
        existing_verification
        is not None
        and existing_verification
        .verified_at
        is not None
        and existing_verification
        .invalidated_at
        is None
    ):
        raise TripPinStateError(
            "A verified trip PIN cannot "
            "be rotated."
        )

    pin = generate_trip_pin()

    pin_hash = hash_trip_pin(
        pin=pin,
        assignment_id=(
            assignment.id
        ),
        secret=secret,
    )

    expires_at = (
        now
        + timedelta(
            seconds=(
                policy.ttl_seconds
            )
        )
    )

    if (
        existing_verification
        is None
    ):
        verification = (
            TripStartVerification(
                trip_id=trip.id,
                assignment_id=(
                    assignment.id
                ),
                pin_hash=pin_hash,
                attempt_count=0,
                locked_until=None,
                expires_at=(
                    expires_at
                ),
                verified_at=None,
                invalidated_at=None,
                created_at=now,
            )
        )

    else:
        verification = (
            existing_verification
        )

        if (
            verification.trip_id
            != trip.id
            or verification
            .assignment_id
            != assignment.id
        ):
            raise TripPinStateError(
                "Existing verification does "
                "not match this assignment."
            )

        verification.pin_hash = (
            pin_hash
        )

        verification.attempt_count = 0

        verification.locked_until = None

        verification.expires_at = (
            expires_at
        )

        verification.verified_at = None

        verification.invalidated_at = None

    return TripPinIssueResult(
        verification=verification,
        pin=pin,
    )


def check_trip_start_pin(
    *,
    verification: TripStartVerification,
    submitted_pin: str,
    now: datetime | None = None,
    secret: str | None = None,
    policy: TripPinPolicy = (
        ABUJA_TRIP_PIN_POLICY
    ),
) -> TripPinCheckResult:
    now = (
        now
        or datetime.now(UTC)
    )

    if (
        verification.invalidated_at
        is not None
    ):
        raise TripPinInvalidatedError(
            "Trip PIN has been invalidated."
        )

    if (
        verification.verified_at
        is not None
    ):
        raise (
            TripPinAlreadyVerifiedError(
                "Trip PIN has already "
                "been verified."
            )
        )

    if (
        now
        >= verification.expires_at
    ):
        raise TripPinExpiredError(
            "Trip PIN has expired."
        )

    if (
        verification.locked_until
        is not None
    ):
        if (
            now
            < verification.locked_until
        ):
            raise TripPinLockedError(
                "Trip PIN verification is "
                "temporarily locked."
            )

        verification.attempt_count = 0
        verification.locked_until = None

    if trip_pin_matches(
        pin=submitted_pin,
        pin_hash=(
            verification.pin_hash
        ),
        assignment_id=(
            verification.assignment_id
        ),
        secret=secret,
    ):
        verification.verified_at = now

        return TripPinCheckResult(
            verified=True,
            attempt_count=(
                verification
                .attempt_count
            ),
            attempts_remaining=(
                max(
                    0,
                    policy.max_attempts
                    - verification
                    .attempt_count
                )
            ),
            locked_until=None,
        )

    verification.attempt_count += 1

    attempts_remaining = max(
        0,
        (
            policy.max_attempts
            - verification
            .attempt_count
        ),
    )

    if (
        verification.attempt_count
        >= policy.max_attempts
    ):
        verification.locked_until = (
            now
            + timedelta(
                seconds=(
                    policy.lock_seconds
                )
            )
        )

    return TripPinCheckResult(
        verified=False,
        attempt_count=(
            verification.attempt_count
        ),
        attempts_remaining=(
            attempts_remaining
        ),
        locked_until=(
            verification.locked_until
        ),
    )


def ensure_trip_start_authorized(
    *,
    trip: Trip,
    assignment: DriverAssignment,
    verification: TripStartVerification,
    now: datetime | None = None,
) -> None:
    now = (
        now
        or datetime.now(UTC)
    )

    _validate_trip_assignment(
        trip=trip,
        assignment=assignment,
    )

    if (
        trip.status
        != "driver_arrived"
    ):
        raise TripStartAuthorizationError(
            "Trip must be in "
            "driver_arrived state "
            "before starting."
        )

    if (
        verification.trip_id
        != trip.id
        or verification
        .assignment_id
        != assignment.id
    ):
        raise TripStartAuthorizationError(
            "Trip PIN verification does "
            "not belong to the active "
            "assignment."
        )

    if (
        verification.invalidated_at
        is not None
    ):
        raise TripStartAuthorizationError(
            "Trip PIN verification "
            "has been invalidated."
        )

    if (
        now
        >= verification.expires_at
    ):
        raise TripStartAuthorizationError(
            "Trip PIN verification "
            "has expired."
        )

    if (
        verification.verified_at
        is None
    ):
        raise TripStartAuthorizationError(
            "Trip PIN has not been "
            "verified."
        )


def invalidate_trip_start_verification(
    *,
    verification: TripStartVerification,
    now: datetime | None = None,
) -> None:
    if (
        verification.invalidated_at
        is not None
    ):
        return

    verification.invalidated_at = (
        now
        or datetime.now(UTC)
    )