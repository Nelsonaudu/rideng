from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification_outbox import (
    NotificationOutbox,
)
from app.services.ride_policy import (
    IntermediateStopWaitingPolicy,
)


def _dedupe_key(
    *,
    trip_id: UUID,
    stop_id: UUID,
    event: str,
) -> str:
    return (
        f"trip:{trip_id}:"
        f"stop:{stop_id}:"
        f"{event}"
    )


def _existing_by_dedupe_key(
    *,
    db: Session,
    dedupe_key: str,
) -> NotificationOutbox | None:
    return db.scalar(
        select(
            NotificationOutbox
        ).where(
            NotificationOutbox.dedupe_key
            == dedupe_key
        )
    )


def _get_or_create(
    *,
    db: Session,
    rider_id: UUID,
    trip_id: UUID,
    stop_id: UUID,
    notification_type: str,
    dedupe_key: str,
    scheduled_for: datetime,
    payload: dict,
) -> NotificationOutbox:
    existing = _existing_by_dedupe_key(
        db=db,
        dedupe_key=dedupe_key,
    )

    if existing is not None:
        return existing

    row = NotificationOutbox(
        user_id=rider_id,
        trip_id=trip_id,
        stop_id=stop_id,
        notification_type=(
            notification_type
        ),
        dedupe_key=dedupe_key,
        scheduled_for=scheduled_for,
        payload=payload,
        status="pending",
    )

    db.add(row)
    db.flush()

    return row


def schedule_stop_arrival_notifications(
    *,
    db: Session,
    rider_id: UUID,
    trip_id: UUID,
    stop_id: UUID,
    arrived_at: datetime,
    policy: IntermediateStopWaitingPolicy,
) -> list[NotificationOutbox]:
    free_wait_seconds = (
        policy.free_wait_seconds
    )

    exit_right_seconds = (
        policy.driver_exit_right_seconds
    )

    free_wait_warning_seconds = max(
        0,
        free_wait_seconds - 60,
    )

    exit_warning_2m_seconds = max(
        free_wait_seconds,
        exit_right_seconds - 120,
    )

    exit_warning_1m_seconds = max(
        free_wait_seconds,
        exit_right_seconds - 60,
    )

    definitions = [
        (
            "intermediate_stop_arrived",
            0,
            "arrival",
            {
                "event": "intermediate_stop_arrived",
                "free_wait_seconds": (
                    free_wait_seconds
                ),
                "wait_rate_per_minute": str(
                    policy.wait_rate_per_minute
                ),
                "driver_exit_right_seconds": (
                    exit_right_seconds
                ),
            },
        ),
        (
            "intermediate_stop_free_wait_warning",
            free_wait_warning_seconds,
            "free-wait-warning",
            {
                "event": (
                    "intermediate_stop_"
                    "free_wait_warning"
                ),
                "seconds_until_paid_wait": (
                    max(
                        0,
                        free_wait_seconds
                        - free_wait_warning_seconds,
                    )
                ),
                "wait_rate_per_minute": str(
                    policy.wait_rate_per_minute
                ),
            },
        ),
        (
            "intermediate_stop_paid_wait_started",
            free_wait_seconds,
            "paid-wait-started",
            {
                "event": (
                    "intermediate_stop_"
                    "paid_wait_started"
                ),
                "wait_rate_per_minute": str(
                    policy.wait_rate_per_minute
                ),
            },
        ),
        (
            "intermediate_stop_exit_warning_2m",
            exit_warning_2m_seconds,
            "exit-warning-2m",
            {
                "event": (
                    "intermediate_stop_"
                    "exit_warning_2m"
                ),
                "seconds_until_exit_right": (
                    max(
                        0,
                        exit_right_seconds
                        - exit_warning_2m_seconds,
                    )
                ),
            },
        ),
        (
            "intermediate_stop_exit_warning_1m",
            exit_warning_1m_seconds,
            "exit-warning-1m",
            {
                "event": (
                    "intermediate_stop_"
                    "exit_warning_1m"
                ),
                "seconds_until_exit_right": (
                    max(
                        0,
                        exit_right_seconds
                        - exit_warning_1m_seconds,
                    )
                ),
            },
        ),
        (
            "intermediate_stop_wait_timeout",
            exit_right_seconds,
            "wait-timeout",
            {
                "event": (
                    "intermediate_stop_"
                    "wait_timeout"
                ),
                "driver_exit_right_available": (
                    True
                ),
                "extension_seconds": (
                    policy.extension_seconds
                ),
            },
        ),
    ]

    rows: list[
        NotificationOutbox
    ] = []

    for (
        notification_type,
        offset_seconds,
        dedupe_suffix,
        payload,
    ) in definitions:
        rows.append(
            _get_or_create(
                db=db,
                rider_id=rider_id,
                trip_id=trip_id,
                stop_id=stop_id,
                notification_type=(
                    notification_type
                ),
                dedupe_key=_dedupe_key(
                    trip_id=trip_id,
                    stop_id=stop_id,
                    event=dedupe_suffix,
                ),
                scheduled_for=(
                    arrived_at
                    + timedelta(
                        seconds=offset_seconds
                    )
                ),
                payload=payload,
            )
        )

    return rows


def schedule_wait_extension_notifications(
    *,
    db: Session,
    rider_id: UUID,
    trip_id: UUID,
    stop_id: UUID,
    extension_number: int,
    extension_started_at: datetime,
    extension_seconds: int,
    wait_rate_per_minute: Decimal,
) -> list[NotificationOutbox]:
    if extension_number < 1:
        raise ValueError(
            "Extension number must be positive."
        )

    if extension_seconds <= 0:
        raise ValueError(
            "Extension duration must be positive."
        )

    if wait_rate_per_minute < 0:
        raise ValueError(
            "Waiting rate cannot be negative."
        )

    extension_ends_at = (
        extension_started_at
        + timedelta(
            seconds=extension_seconds
        )
    )

    warning_at = max(
        extension_started_at,
        extension_ends_at
        - timedelta(seconds=60),
    )

    prefix = (
        f"extension:{extension_number}"
    )

    definitions = [
        (
            "intermediate_stop_extension_started",
            extension_started_at,
            f"{prefix}:started",
            {
                "event": (
                    "intermediate_stop_"
                    "extension_started"
                ),
                "extension_number": (
                    extension_number
                ),
                "extension_seconds": (
                    extension_seconds
                ),
                "wait_rate_per_minute": str(
                    wait_rate_per_minute
                ),
            },
        ),
        (
            (
                "intermediate_stop_"
                "extension_warning_1m"
            ),
            warning_at,
            f"{prefix}:warning-1m",
            {
                "event": (
                    "intermediate_stop_"
                    "extension_warning_1m"
                ),
                "extension_number": (
                    extension_number
                ),
                "seconds_until_extension_end": (
                    max(
                        0,
                        int(
                            (
                                extension_ends_at
                                - warning_at
                            ).total_seconds()
                        ),
                    )
                ),
            },
        ),
        (
            "intermediate_stop_extension_ended",
            extension_ends_at,
            f"{prefix}:ended",
            {
                "event": (
                    "intermediate_stop_"
                    "extension_ended"
                ),
                "extension_number": (
                    extension_number
                ),
            },
        ),
    ]

    rows: list[
        NotificationOutbox
    ] = []

    for (
        notification_type,
        scheduled_for,
        dedupe_suffix,
        payload,
    ) in definitions:
        rows.append(
            _get_or_create(
                db=db,
                rider_id=rider_id,
                trip_id=trip_id,
                stop_id=stop_id,
                notification_type=(
                    notification_type
                ),
                dedupe_key=_dedupe_key(
                    trip_id=trip_id,
                    stop_id=stop_id,
                    event=dedupe_suffix,
                ),
                scheduled_for=scheduled_for,
                payload=payload,
            )
        )

    return rows


def cancel_pending_stop_notifications(
    *,
    db: Session,
    stop_id: UUID,
    now: datetime,
) -> int:
    rows = db.scalars(
        select(
            NotificationOutbox
        ).where(
            NotificationOutbox.stop_id
            == stop_id
        )
    ).all()

    changed = 0

    for row in rows:
        if row.status != "pending":
            continue

        if row.scheduled_for <= now:
            continue

        row.status = "cancelled"
        row.cancelled_at = now

        changed += 1

    if changed:
        db.flush()

    return changed


def schedule_wait_ended_notification(
    *,
    db: Session,
    rider_id: UUID,
    trip_id: UUID,
    stop_id: UUID,
    stopped_at: datetime,
    final_wait_charge: Decimal,
) -> NotificationOutbox:
    if final_wait_charge < 0:
        raise ValueError(
            "Final wait charge cannot be negative."
        )

    return _get_or_create(
        db=db,
        rider_id=rider_id,
        trip_id=trip_id,
        stop_id=stop_id,
        notification_type=(
            "intermediate_stop_wait_ended"
        ),
        dedupe_key=_dedupe_key(
            trip_id=trip_id,
            stop_id=stop_id,
            event="wait-ended",
        ),
        scheduled_for=stopped_at,
        payload={
            "event": (
                "intermediate_stop_wait_ended"
            ),
            "final_wait_charge": str(
                final_wait_charge
            ),
        },
    )
