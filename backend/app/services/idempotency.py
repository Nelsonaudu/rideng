from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.idempotency_record import (
    IdempotencyRecord,
)


DEFAULT_IDEMPOTENCY_TTL_SECONDS = 86400


class IdempotencyError(
    ValueError
):
    pass


class IdempotencyKeyError(
    IdempotencyError
):
    pass


class IdempotencyConflictError(
    IdempotencyError
):
    pass


class IdempotencyInProgressError(
    IdempotencyError
):
    pass


@dataclass(frozen=True)
class IdempotencyResult:
    status_code: int
    body: dict[str, Any]
    replayed: bool


def normalize_idempotency_key(
    key: str,
) -> str:
    normalized = key.strip()

    if not normalized:
        raise IdempotencyKeyError(
            "Idempotency-Key cannot be blank."
        )

    if len(normalized) > 255:
        raise IdempotencyKeyError(
            "Idempotency-Key cannot exceed "
            "255 characters."
        )

    return normalized


def build_request_hash(
    payload: Mapping[str, Any],
) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        default=str,
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        encoded
    ).hexdigest()


def execute_idempotently(
    *,
    db: Session,
    user_id: UUID,
    operation: str,
    idempotency_key: str,
    request_payload: Mapping[str, Any],
    action: Callable[
        [],
        tuple[
            int,
            dict[str, Any],
        ],
    ],
    ttl_seconds: int = (
        DEFAULT_IDEMPOTENCY_TTL_SECONDS
    ),
) -> IdempotencyResult:
    key = normalize_idempotency_key(
        idempotency_key
    )

    request_hash = build_request_hash(
        request_payload
    )

    existing = db.scalar(
        select(
            IdempotencyRecord
        )
        .where(
            IdempotencyRecord.user_id
            == user_id,
            IdempotencyRecord.operation
            == operation,
            IdempotencyRecord.idempotency_key
            == key,
        )
        .with_for_update()
    )

    if existing is not None:
        if (
            existing.request_hash
            != request_hash
        ):
            raise IdempotencyConflictError(
                "Idempotency-Key was already "
                "used with a different request."
            )

        if (
            existing.response_status
            is None
            or existing.response_body
            is None
        ):
            raise IdempotencyInProgressError(
                "An operation with this "
                "Idempotency-Key is already "
                "in progress."
            )

        return IdempotencyResult(
            status_code=(
                existing.response_status
            ),
            body=existing.response_body,
            replayed=True,
        )

    record = IdempotencyRecord(
        user_id=user_id,
        operation=operation,
        idempotency_key=key,
        request_hash=request_hash,
        response_status=None,
        response_body=None,
        expires_at=(
            datetime.now(UTC)
            + timedelta(
                seconds=ttl_seconds
            )
        ),
    )

    db.add(
        record
    )

    try:
        db.flush()

    except IntegrityError as exc:
        raise IdempotencyConflictError(
            "Idempotency-Key is already "
            "being processed."
        ) from exc

    status_code, body = action()

    record.response_status = (
        status_code
    )

    record.response_body = body

    db.flush()

    return IdempotencyResult(
        status_code=status_code,
        body=body,
        replayed=False,
    )