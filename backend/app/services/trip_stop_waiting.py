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
