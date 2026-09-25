from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol


MONEY_QUANTUM = Decimal("0.01")
SECONDS_PER_MINUTE = Decimal("60")


class WaitStateLike(Protocol):
    arrived_at: datetime
    free_wait_ends_at: datetime
    driver_exit_right_at: datetime

    current_paid_window_started_at: datetime | None
    authorized_until: datetime | None

    accrued_billable_seconds: int
    wait_rate_per_minute: Decimal


@dataclass(frozen=True)
class WaitMeterSnapshot:
    billable_seconds: int
    gross_wait_charge: Decimal

    free_wait_ends_at: datetime
    driver_exit_right_at: datetime
    authorized_until: datetime | None

    exit_right_available: bool
    extension_available: bool


def _whole_elapsed_seconds(
    *,
    start: datetime,
    end: datetime,
) -> int:
    if end <= start:
        return 0

    return max(
        0,
        int(
            (end - start).total_seconds()
        ),
    )


def gross_wait_charge(
    *,
    billable_seconds: int,
    rate_per_minute: Decimal,
) -> Decimal:
    if billable_seconds < 0:
        raise ValueError(
            "Billable seconds cannot be negative."
        )

    if rate_per_minute < 0:
        raise ValueError(
            "Waiting rate cannot be negative."
        )

    amount = (
        Decimal(billable_seconds)
        * rate_per_minute
        / SECONDS_PER_MINUTE
    )

    return amount.quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def calculate_wait_meter(
    *,
    state: WaitStateLike,
    now: datetime,
) -> WaitMeterSnapshot:
    if state.accrued_billable_seconds < 0:
        raise ValueError(
            "Accrued billable seconds "
            "cannot be negative."
        )

    billable_seconds = (
        state.accrued_billable_seconds
    )

    window_start = (
        state.current_paid_window_started_at
    )

    authorized_until = (
        state.authorized_until
    )

    if (
        window_start is not None
        and authorized_until is not None
        and authorized_until < window_start
    ):
        raise ValueError(
            "Authorized waiting window cannot "
            "end before it starts."
        )

    if (
        window_start is not None
        and authorized_until is not None
    ):
        effective_end = min(
            now,
            authorized_until,
        )

        billable_seconds += (
            _whole_elapsed_seconds(
                start=window_start,
                end=effective_end,
            )
        )

    exit_right_available = (
        now >= state.driver_exit_right_at
    )

    extension_available = (
        exit_right_available
        and (
            authorized_until is None
            or now >= authorized_until
        )
    )

    return WaitMeterSnapshot(
        billable_seconds=billable_seconds,
        gross_wait_charge=gross_wait_charge(
            billable_seconds=billable_seconds,
            rate_per_minute=(
                state.wait_rate_per_minute
            ),
        ),
        free_wait_ends_at=(
            state.free_wait_ends_at
        ),
        driver_exit_right_at=(
            state.driver_exit_right_at
        ),
        authorized_until=authorized_until,
        exit_right_available=(
            exit_right_available
        ),
        extension_available=(
            extension_available
        ),
    )
# ---------------------------------------------------------------------------
# Batch 9 authoritative intermediate-stop waiting lifecycle
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _lifecycle_dataclass
from datetime import datetime as _lifecycle_datetime, timedelta
from decimal import (
    Decimal as _LifecycleDecimal,
    ROUND_HALF_UP as _LIFECYCLE_ROUND_HALF_UP,
)
from uuid import UUID as _LifecycleUUID

from sqlalchemy import select as _lifecycle_select
from sqlalchemy.orm import Session as _LifecycleSession

from app.models.driver_assignment import DriverAssignment as _LifecycleAssignment
from app.models.trip import Trip as _LifecycleTrip
from app.models.trip_event import TripEvent as _LifecycleTripEvent
from app.models.trip_stop import TripStop as _LifecycleTripStop
from app.models.trip_stop_wait_state import (
    TripStopWaitState as _LifecycleWaitState,
)
from app.services.notification_outbox import (
    cancel_pending_stop_notifications as _cancel_pending_stop_notifications,
    schedule_wait_ended_notification as _schedule_wait_ended_notification,
    schedule_wait_extension_notifications as _schedule_wait_extension_notifications,
)


@_lifecycle_dataclass(frozen=True)
class StopWaitClosureResult:
    stop_id: _LifecycleUUID
    final_billable_seconds: int
    final_wait_charge: _LifecycleDecimal
    closed_at: _lifecycle_datetime
    close_reason: str


@_lifecycle_dataclass(frozen=True)
class StopWaitExtensionResult:
    stop_id: _LifecycleUUID
    extension_number: int
    billable_seconds: int
    gross_wait_charge: _LifecycleDecimal
    authorized_until: _lifecycle_datetime


def _wait_charge(
    *,
    billable_seconds: int,
    wait_rate_per_minute: _LifecycleDecimal,
) -> _LifecycleDecimal:
    if billable_seconds <= 0:
        return _LifecycleDecimal("0.00")

    charge = (
        _LifecycleDecimal(
            billable_seconds
        )
        * wait_rate_per_minute
        / _LifecycleDecimal("60")
    )

    return charge.quantize(
        _LifecycleDecimal("0.01"),
        rounding=_LIFECYCLE_ROUND_HALF_UP,
    )


def _window_billable_seconds(
    *,
    wait: _LifecycleWaitState,
    now: _lifecycle_datetime,
) -> int:
    started_at = (
        wait.current_paid_window_started_at
    )

    authorized_until = (
        wait.authorized_until
    )

    if (
        started_at is None
        or authorized_until is None
    ):
        return 0

    if now <= started_at:
        return 0

    bounded_end = min(
        now,
        authorized_until,
    )

    if bounded_end <= started_at:
        return 0

    return max(
        0,
        int(
            (
                bounded_end
                - started_at
            ).total_seconds()
        ),
    )


def _validate_wait_actor(
    *,
    trip: _LifecycleTrip,
    assignment: _LifecycleAssignment,
    rider_id: _LifecycleUUID,
) -> None:
    if trip.status != "in_progress":
        raise ValueError(
            "Trip must be in progress."
        )

    if (
        trip.active_assignment_id
        != assignment.id
    ):
        raise ValueError(
            "Driver assignment is not "
            "the active trip assignment."
        )

    if assignment.status != "active":
        raise ValueError(
            "Driver assignment is not active."
        )

    if (
        assignment.ride_request_id
        != trip.ride_request_id
    ):
        raise ValueError(
            "Driver assignment does not "
            "belong to this trip."
        )

    if rider_id != trip.rider_id:
        raise ValueError(
            "Rider does not own this trip."
        )


def _wait_contexts(
    *,
    db: _LifecycleSession,
    trip: _LifecycleTrip,
    assignment: _LifecycleAssignment,
):
    waits = db.scalars(
        _lifecycle_select(
            _LifecycleWaitState
        )
        .where(
            _LifecycleWaitState.trip_id
            == trip.id,
            _LifecycleWaitState.assignment_id
            == assignment.id,
        )
        .with_for_update()
    ).all()

    contexts = []

    for wait in waits:
        stop = db.scalar(
            _lifecycle_select(
                _LifecycleTripStop
            )
            .where(
                _LifecycleTripStop.id
                == wait.stop_id
            )
            .with_for_update()
        )

        if stop is None:
            continue

        if (
            stop.trip_id != trip.id
            or stop.stop_type
            != "intermediate"
        ):
            continue

        contexts.append(
            (
                stop,
                wait,
            )
        )

    return contexts


def _open_wait_context(
    *,
    db: _LifecycleSession,
    trip: _LifecycleTrip,
    assignment: _LifecycleAssignment,
):
    contexts = _wait_contexts(
        db=db,
        trip=trip,
        assignment=assignment,
    )

    open_contexts = [
        context
        for context in contexts
        if (
            context[1].closed_at
            is None
            and context[0].departed_at
            is None
        )
    ]

    if not open_contexts:
        raise ValueError(
            "No active intermediate-stop "
            "waiting state exists."
        )

    open_contexts.sort(
        key=lambda context: (
            context[0].sequence
        )
    )

    return open_contexts[0]


def _closed_retry_context(
    *,
    db: _LifecycleSession,
    trip: _LifecycleTrip,
    assignment: _LifecycleAssignment,
    close_reason: str,
):
    contexts = _wait_contexts(
        db=db,
        trip=trip,
        assignment=assignment,
    )

    matches = [
        context
        for context in contexts
        if (
            context[1].closed_at
            is not None
            and context[1].close_reason
            == close_reason
        )
    ]

    if not matches:
        return None

    matches.sort(
        key=lambda context: (
            context[1].closed_at
        ),
        reverse=True,
    )

    return matches[0]


def _stored_closure_result(
    *,
    stop: _LifecycleTripStop,
    wait: _LifecycleWaitState,
) -> StopWaitClosureResult:
    if wait.closed_at is None:
        raise ValueError(
            "Waiting state is not closed."
        )

    return StopWaitClosureResult(
        stop_id=stop.id,
        final_billable_seconds=(
            wait.final_billable_seconds
            or 0
        ),
        final_wait_charge=(
            wait.final_wait_charge
            or _LifecycleDecimal(
                "0.00"
            )
        ),
        closed_at=wait.closed_at,
        close_reason=(
            wait.close_reason
            or "unknown"
        ),
    )


def _record_wait_event(
    *,
    db: _LifecycleSession,
    trip: _LifecycleTrip,
    assignment: _LifecycleAssignment,
    event_type: str,
    event_data: dict,
    now: _lifecycle_datetime,
) -> None:
    db.add(
        _LifecycleTripEvent(
            ride_request_id=(
                trip.ride_request_id
            ),
            trip_id=trip.id,
            actor_user_id=(
                assignment.driver_id
            ),
            event_type=event_type,
            event_data=event_data,
            created_at=now,
        )
    )


def _close_wait(
    *,
    db: _LifecycleSession,
    trip: _LifecycleTrip,
    assignment: _LifecycleAssignment,
    rider_id: _LifecycleUUID,
    stop: _LifecycleTripStop,
    wait: _LifecycleWaitState,
    now: _lifecycle_datetime,
    close_reason: str,
) -> StopWaitClosureResult:
    current_seconds = (
        _window_billable_seconds(
            wait=wait,
            now=now,
        )
    )

    final_billable_seconds = (
        wait.accrued_billable_seconds
        + current_seconds
    )

    final_wait_charge = _wait_charge(
        billable_seconds=(
            final_billable_seconds
        ),
        wait_rate_per_minute=(
            wait.wait_rate_per_minute
        ),
    )

    wait.final_billable_seconds = (
        final_billable_seconds
    )

    wait.final_wait_charge = (
        final_wait_charge
    )

    wait.closed_at = now
    wait.close_reason = close_reason

    wait.current_paid_window_started_at = (
        None
    )

    wait.authorized_until = None
    wait.updated_at = now

    if (
        final_billable_seconds > 0
        and stop.paid_wait_started_at
        is None
    ):
        stop.paid_wait_started_at = (
            wait.free_wait_ends_at
        )

    if stop.departed_at is None:
        stop.departed_at = now

    _cancel_pending_stop_notifications(
        db=db,
        stop_id=stop.id,
        now=now,
    )

    _schedule_wait_ended_notification(
        db=db,
        rider_id=rider_id,
        trip_id=trip.id,
        stop_id=stop.id,
        stopped_at=now,
        final_wait_charge=(
            final_wait_charge
        ),
    )

    _record_wait_event(
        db=db,
        trip=trip,
        assignment=assignment,
        event_type=(
            "intermediate_stop_departed"
        ),
        event_data={
            "stop_id": str(
                stop.id
            ),
            "stop_sequence": (
                stop.sequence
            ),
            "assignment_id": str(
                assignment.id
            ),
            "close_reason": (
                close_reason
            ),
            "departed_at": (
                now.isoformat()
            ),
            "final_billable_seconds": (
                final_billable_seconds
            ),
            "final_wait_charge": str(
                final_wait_charge
            ),
        },
        now=now,
    )

    db.flush()

    return StopWaitClosureResult(
        stop_id=stop.id,
        final_billable_seconds=(
            final_billable_seconds
        ),
        final_wait_charge=(
            final_wait_charge
        ),
        closed_at=now,
        close_reason=close_reason,
    )


def depart_current_intermediate_stop(
    *,
    db: _LifecycleSession,
    trip: _LifecycleTrip,
    assignment: _LifecycleAssignment,
    rider_id: _LifecycleUUID,
    now: _lifecycle_datetime,
) -> StopWaitClosureResult:
    _validate_wait_actor(
        trip=trip,
        assignment=assignment,
        rider_id=rider_id,
    )

    try:
        stop, wait = _open_wait_context(
            db=db,
            trip=trip,
            assignment=assignment,
        )

    except ValueError:
        retry = _closed_retry_context(
            db=db,
            trip=trip,
            assignment=assignment,
            close_reason="departed",
        )

        if retry is None:
            raise

        stop, wait = retry

        return _stored_closure_result(
            stop=stop,
            wait=wait,
        )

    if now < wait.arrived_at:
        raise ValueError(
            "Departure cannot precede arrival."
        )

    return _close_wait(
        db=db,
        trip=trip,
        assignment=assignment,
        rider_id=rider_id,
        stop=stop,
        wait=wait,
        now=now,
        close_reason="departed",
    )


def authorize_current_stop_wait_extension(
    *,
    db: _LifecycleSession,
    trip: _LifecycleTrip,
    assignment: _LifecycleAssignment,
    rider_id: _LifecycleUUID,
    now: _lifecycle_datetime,
) -> StopWaitExtensionResult:
    _validate_wait_actor(
        trip=trip,
        assignment=assignment,
        rider_id=rider_id,
    )

    stop, wait = _open_wait_context(
        db=db,
        trip=trip,
        assignment=assignment,
    )

    if wait.closed_at is not None:
        raise ValueError(
            "Closed waiting state "
            "cannot be extended."
        )

    authorized_until = (
        wait.authorized_until
    )

    if authorized_until is None:
        raise ValueError(
            "Waiting state has no "
            "active authorization window."
        )

    if now < authorized_until:
        raise ValueError(
            "Waiting extension is not "
            "available yet."
        )

    completed_window_seconds = (
        _window_billable_seconds(
            wait=wait,
            now=now,
        )
    )

    wait.accrued_billable_seconds = (
        wait.accrued_billable_seconds
        + completed_window_seconds
    )

    wait.extension_count = (
        wait.extension_count + 1
    )

    extension_number = (
        wait.extension_count
    )

    wait.current_paid_window_started_at = (
        now
    )

    wait.authorized_until = (
        now
        + timedelta(
            seconds=(
                wait.extension_seconds
            )
        )
    )

    wait.updated_at = now

    if stop.paid_wait_started_at is None:
        stop.paid_wait_started_at = (
            wait.free_wait_ends_at
        )

    gross_wait_charge = _wait_charge(
        billable_seconds=(
            wait.accrued_billable_seconds
        ),
        wait_rate_per_minute=(
            wait.wait_rate_per_minute
        ),
    )

    _schedule_wait_extension_notifications(
        db=db,
        rider_id=rider_id,
        trip_id=trip.id,
        stop_id=stop.id,
        extension_number=(
            extension_number
        ),
        extension_started_at=now,
        extension_seconds=(
            wait.extension_seconds
        ),
        wait_rate_per_minute=(
            wait.wait_rate_per_minute
        ),
    )

    _record_wait_event(
        db=db,
        trip=trip,
        assignment=assignment,
        event_type=(
            "intermediate_stop_wait_extended"
        ),
        event_data={
            "stop_id": str(
                stop.id
            ),
            "stop_sequence": (
                stop.sequence
            ),
            "assignment_id": str(
                assignment.id
            ),
            "extension_number": (
                extension_number
            ),
            "extension_seconds": (
                wait.extension_seconds
            ),
            "authorized_until": (
                wait
                .authorized_until
                .isoformat()
            ),
            "accrued_billable_seconds": (
                wait
                .accrued_billable_seconds
            ),
            "gross_wait_charge": str(
                gross_wait_charge
            ),
        },
        now=now,
    )

    db.flush()

    return StopWaitExtensionResult(
        stop_id=stop.id,
        extension_number=(
            extension_number
        ),
        billable_seconds=(
            wait.accrued_billable_seconds
        ),
        gross_wait_charge=(
            gross_wait_charge
        ),
        authorized_until=(
            wait.authorized_until
        ),
    )


def exercise_current_stop_exit_right(
    *,
    db: _LifecycleSession,
    trip: _LifecycleTrip,
    assignment: _LifecycleAssignment,
    rider_id: _LifecycleUUID,
    now: _lifecycle_datetime,
) -> StopWaitClosureResult:
    _validate_wait_actor(
        trip=trip,
        assignment=assignment,
        rider_id=rider_id,
    )

    try:
        stop, wait = _open_wait_context(
            db=db,
            trip=trip,
            assignment=assignment,
        )

    except ValueError:
        retry = _closed_retry_context(
            db=db,
            trip=trip,
            assignment=assignment,
            close_reason=(
                "driver_exit_right"
            ),
        )

        if retry is None:
            raise

        stop, wait = retry

        return _stored_closure_result(
            stop=stop,
            wait=wait,
        )

    authorized_until = (
        wait.authorized_until
    )

    if authorized_until is None:
        raise ValueError(
            "Waiting state has no "
            "active authorization window."
        )

    if now < authorized_until:
        raise ValueError(
            "Driver exit right is "
            "not available yet."
        )

    return _close_wait(
        db=db,
        trip=trip,
        assignment=assignment,
        rider_id=rider_id,
        stop=stop,
        wait=wait,
        now=now,
        close_reason=(
            "driver_exit_right"
        ),
    )


def terminate_at_current_stop(
    *,
    db: _LifecycleSession,
    trip: _LifecycleTrip,
    assignment: _LifecycleAssignment,
    rider_id: _LifecycleUUID,
    now: _lifecycle_datetime,
) -> StopWaitClosureResult:
    """
    End an in-progress trip at the authoritative current
    intermediate stop after the original exit-right boundary.

    The driver's exit right, once earned, remains available even
    during a voluntarily-authorized extension.
    """
    _validate_wait_actor(
        trip=trip,
        assignment=assignment,
        rider_id=rider_id,
    )

    stop, wait = _open_wait_context(
        db=db,
        trip=trip,
        assignment=assignment,
    )

    exit_right_at = (
        wait.driver_exit_right_at
    )

    if (
        exit_right_at is None
        or now < exit_right_at
    ):
        raise ValueError(
            "Driver exit right is not "
            "available yet."
        )

    result = _close_wait(
        db=db,
        trip=trip,
        assignment=assignment,
        rider_id=rider_id,
        stop=stop,
        wait=wait,
        now=now,
        close_reason=(
            "intermediate_stop_wait_timeout"
        ),
    )

    assignment.status = "completed"

    trip.status = "terminated"
    trip.active_assignment_id = None

    _record_wait_event(
        db=db,
        trip=trip,
        assignment=assignment,
        event_type=(
            "intermediate_stop_wait_timeout"
        ),
        event_data={
            "stop_id": str(stop.id),
            "stop_sequence": (
                stop.sequence
            ),
            "assignment_id": str(
                assignment.id
            ),
            "termination_reason": (
                "intermediate_stop_wait_timeout"
            ),
            "terminated_at": (
                now.isoformat()
            ),
            "billable_seconds": (
                result.final_billable_seconds
            ),
            "gross_wait_charge": str(
                result.final_wait_charge
            ),
            "extension_count": (
                wait.extension_count
            ),
            "original_agreed_fare": str(
                trip.agreed_fare
            ),
        },
        now=now,
    )

    db.flush()

    return result
