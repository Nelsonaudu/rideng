from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.driver_assignment import (
    DriverAssignment,
)
from app.models.trip import Trip
from app.models.trip_event import TripEvent
from app.models.trip_stop import TripStop
from app.models.trip_stop_location_verification import (
    TripStopLocationVerificationState,
)
from app.models.trip_stop_wait_state import (
    TripStopWaitState,
)
from app.services.location_verification import (
    ArrivalLocationPolicy,
    LocationSample,
    LocationSampleConflictError,
    advance_arrival_confirmation,
    validate_location_sample,
)
from app.services.notification_outbox import (
    schedule_stop_arrival_notifications,
)
from app.services.ride_policy import (
    ABUJA_INTERMEDIATE_STOP_WAIT_POLICY,
)


ABUJA_INTERMEDIATE_STOP_LOCATION_POLICY = (
    ArrivalLocationPolicy(
        arrival_radius_m=100.0,
        max_horizontal_accuracy_m=50.0,
        max_sample_age_seconds=15,
        max_future_skew_seconds=5,
        min_confirmation_separation_seconds=3,
        max_confirmation_separation_seconds=10,
        max_plausible_speed_mps=55.0,
    )
)


@dataclass(frozen=True)
class StopLocationResult:
    replayed: bool

    stop_id: UUID
    stop_sequence: int

    distance_to_stop_m: float

    arrival_candidate_count: int

    arrival_verified: bool
    arrival_newly_verified: bool


def get_current_intermediate_stop(
    *,
    db: Session,
    trip_id: UUID,
    lock: bool = False,
) -> TripStop | None:
    statement = (
        select(
            TripStop
        )
        .where(
            TripStop.trip_id == trip_id,
            TripStop.stop_type
            == "intermediate",
            TripStop.departed_at.is_(
                None
            ),
        )
        .order_by(
            TripStop.sequence.asc()
        )
        .limit(1)
    )

    if lock:
        statement = (
            statement.with_for_update()
        )

    return db.scalar(
        statement
    )


def _get_location_state(
    *,
    db: Session,
    stop: TripStop,
    trip: Trip,
    assignment: DriverAssignment,
    now: datetime,
) -> TripStopLocationVerificationState:
    statement = (
        select(
            TripStopLocationVerificationState
        )
        .where(
            TripStopLocationVerificationState
            .stop_id
            == stop.id
        )
        .with_for_update()
    )

    state = db.scalar(
        statement
    )

    if state is None:
        state = (
            TripStopLocationVerificationState(
                stop_id=stop.id,
                trip_id=trip.id,
                assignment_id=(
                    assignment.id
                ),
                last_sample_id=None,
                last_latitude=None,
                last_longitude=None,
                last_horizontal_accuracy_m=None,
                last_distance_to_stop_m=None,
                last_sample_captured_at=None,
                last_sample_received_at=None,
                arrival_candidate_count=0,
                last_arrival_candidate_at=None,
                arrival_verified_at=None,
                created_at=now,
                updated_at=now,
            )
        )

        db.add(
            state
        )

        db.flush()

        return state

    if (
        state.assignment_id
        != assignment.id
    ):
        state.assignment_id = (
            assignment.id
        )

        state.trip_id = (
            trip.id
        )

        state.last_sample_id = None
        state.last_latitude = None
        state.last_longitude = None

        state.last_horizontal_accuracy_m = (
            None
        )

        state.last_distance_to_stop_m = (
            None
        )

        state.last_sample_captured_at = (
            None
        )

        state.last_sample_received_at = (
            None
        )

        state.arrival_candidate_count = 0

        state.last_arrival_candidate_at = (
            None
        )

        state.arrival_verified_at = (
            None
        )

        state.updated_at = now

    return state


def _previous_sample(
    *,
    state: TripStopLocationVerificationState,
    current_sample: LocationSample,
) -> LocationSample | None:
    if state.last_sample_id is None:
        return None

    required = (
        state.last_latitude,
        state.last_longitude,
        state.last_horizontal_accuracy_m,
        state.last_sample_captured_at,
    )

    if any(
        value is None
        for value in required
    ):
        raise LocationSampleConflictError(
            "Stored stop location sample "
            "is incomplete."
        )

    return LocationSample(
        sample_id=(
            state.last_sample_id
        ),
        latitude=(
            state.last_latitude
        ),
        longitude=(
            state.last_longitude
        ),
        horizontal_accuracy_m=(
            state
            .last_horizontal_accuracy_m
        ),
        captured_at=(
            state.last_sample_captured_at
        ),
        # These values are intentionally
        # not persisted in the bounded
        # stop-location state. Supplying
        # the current values preserves
        # sample replay semantics without
        # expanding retained location data.
        reported_speed_mps=(
            current_sample
            .reported_speed_mps
        ),
        is_mocked=(
            current_sample.is_mocked
        ),
    )


def _get_wait_state(
    *,
    db: Session,
    stop_id: UUID,
) -> TripStopWaitState | None:
    return db.scalar(
        select(
            TripStopWaitState
        )
        .where(
            TripStopWaitState.stop_id
            == stop_id
        )
        .with_for_update()
    )


def _activate_waiting(
    *,
    db: Session,
    trip: Trip,
    stop: TripStop,
    assignment: DriverAssignment,
    rider_id: UUID,
    arrived_at: datetime,
) -> TripStopWaitState:
    existing = _get_wait_state(
        db=db,
        stop_id=stop.id,
    )

    if existing is not None:
        return existing

    policy = (
        ABUJA_INTERMEDIATE_STOP_WAIT_POLICY
    )

    free_wait_ends_at = (
        arrived_at
        + timedelta(
            seconds=(
                policy.free_wait_seconds
            )
        )
    )

    driver_exit_right_at = (
        arrived_at
        + timedelta(
            seconds=(
                policy
                .driver_exit_right_seconds
            )
        )
    )

    wait_state = TripStopWaitState(
        stop_id=stop.id,
        trip_id=trip.id,
        assignment_id=(
            assignment.id
        ),
        free_wait_seconds=(
            policy.free_wait_seconds
        ),
        wait_rate_per_minute=(
            policy.wait_rate_per_minute
        ),
        driver_exit_right_seconds=(
            policy
            .driver_exit_right_seconds
        ),
        extension_seconds=(
            policy.extension_seconds
        ),
        arrived_at=arrived_at,
        free_wait_ends_at=(
            free_wait_ends_at
        ),
        driver_exit_right_at=(
            driver_exit_right_at
        ),
        current_paid_window_started_at=(
            free_wait_ends_at
        ),
        authorized_until=(
            driver_exit_right_at
        ),
        accrued_billable_seconds=0,
        extension_count=0,
        final_billable_seconds=None,
        final_wait_charge=None,
        closed_at=None,
        close_reason=None,
        created_at=arrived_at,
        updated_at=arrived_at,
    )

    db.add(
        wait_state
    )

    schedule_stop_arrival_notifications(
        db=db,
        rider_id=rider_id,
        trip_id=trip.id,
        stop_id=stop.id,
        arrived_at=arrived_at,
        policy=policy,
    )

    db.add(
        TripEvent(
            ride_request_id=(
                trip.ride_request_id
            ),
            trip_id=trip.id,
            actor_user_id=(
                assignment.driver_id
            ),
            event_type=(
                "intermediate_stop_arrived"
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
                "arrived_at": (
                    arrived_at.isoformat()
                ),
                "free_wait_seconds": (
                    policy
                    .free_wait_seconds
                ),
                "wait_rate_per_minute": str(
                    policy
                    .wait_rate_per_minute
                ),
                "driver_exit_right_seconds": (
                    policy
                    .driver_exit_right_seconds
                ),
            },
            created_at=arrived_at,
        )
    )

    db.flush()

    return wait_state


def _redact_transient_location(
    *,
    state: TripStopLocationVerificationState,
    now: datetime,
) -> None:
    state.last_sample_id = None

    state.last_latitude = None
    state.last_longitude = None

    state.last_horizontal_accuracy_m = (
        None
    )

    state.last_distance_to_stop_m = (
        None
    )

    state.last_sample_captured_at = (
        None
    )

    state.last_sample_received_at = (
        None
    )

    state.updated_at = now


def process_current_stop_location(
    *,
    db: Session,
    trip: Trip,
    assignment: DriverAssignment,
    rider_id: UUID,
    sample: LocationSample,
    now: datetime | None = None,
) -> StopLocationResult:
    now = (
        now
        or datetime.now(UTC)
    )

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

    stop = (
        get_current_intermediate_stop(
            db=db,
            trip_id=trip.id,
            lock=True,
        )
    )

    if stop is None:
        raise ValueError(
            "Trip has no current "
            "intermediate stop."
        )

    state = _get_location_state(
        db=db,
        stop=stop,
        trip=trip,
        assignment=assignment,
        now=now,
    )

    previous_sample = (
        _previous_sample(
            state=state,
            current_sample=sample,
        )
    )

    validation = (
        validate_location_sample(
            sample=sample,
            target_latitude=(
                stop.latitude
            ),
            target_longitude=(
                stop.longitude
            ),
            previous_sample=(
                previous_sample
            ),
            now=now,
            policy=(
                ABUJA_INTERMEDIATE_STOP_LOCATION_POLICY
            ),
        )
    )

    if validation.replayed:
        return StopLocationResult(
            replayed=True,
            stop_id=stop.id,
            stop_sequence=(
                stop.sequence
            ),
            distance_to_stop_m=(
                validation
                .distance_to_target_m
            ),
            arrival_candidate_count=(
                state
                .arrival_candidate_count
            ),
            arrival_verified=(
                state.arrival_verified_at
                is not None
            ),
            arrival_newly_verified=False,
        )

    confirmation = (
        advance_arrival_confirmation(
            candidate_count=(
                state
                .arrival_candidate_count
            ),
            last_candidate_at=(
                state
                .last_arrival_candidate_at
            ),
            already_verified=(
                state.arrival_verified_at
                is not None
            ),
            distance_to_target_m=(
                validation
                .distance_to_target_m
            ),
            horizontal_accuracy_m=(
                sample
                .horizontal_accuracy_m
            ),
            captured_at=(
                sample.captured_at
            ),
            policy=(
                ABUJA_INTERMEDIATE_STOP_LOCATION_POLICY
            ),
        )
    )

    state.last_sample_id = (
        sample.sample_id
    )

    state.last_latitude = (
        sample.latitude
    )

    state.last_longitude = (
        sample.longitude
    )

    state.last_horizontal_accuracy_m = (
        sample
        .horizontal_accuracy_m
    )

    state.last_distance_to_stop_m = (
        Decimal(
            str(
                round(
                    validation
                    .distance_to_target_m,
                    2,
                )
            )
        )
    )

    state.last_sample_captured_at = (
        sample.captured_at
    )

    state.last_sample_received_at = (
        now
    )

    state.arrival_candidate_count = (
        confirmation.candidate_count
    )

    state.last_arrival_candidate_at = (
        confirmation
        .last_candidate_at
    )

    state.updated_at = now

    if (
        confirmation
        .arrival_newly_verified
    ):
        state.arrival_verified_at = (
            now
        )

        if stop.arrived_at is None:
            stop.arrived_at = now

        # This marker intentionally remains
        # NULL at arrival. It is a denormalized
        # audit marker and will be set later by
        # the waiting lifecycle only when paid
        # waiting becomes consequential.
        stop.paid_wait_started_at = (
            None
        )

        _activate_waiting(
            db=db,
            trip=trip,
            stop=stop,
            assignment=assignment,
            rider_id=rider_id,
            arrived_at=now,
        )

        # Exact driver coordinates are needed
        # only transiently to prove arrival.
        # Once durable arrival state exists,
        # remove them from persistent state.
        _redact_transient_location(
            state=state,
            now=now,
        )

    db.flush()

    return StopLocationResult(
        replayed=False,
        stop_id=stop.id,
        stop_sequence=(
            stop.sequence
        ),
        distance_to_stop_m=(
            validation
            .distance_to_target_m
        ),
        arrival_candidate_count=(
            state
            .arrival_candidate_count
        ),
        arrival_verified=(
            state.arrival_verified_at
            is not None
        ),
        arrival_newly_verified=(
            confirmation
            .arrival_newly_verified
        ),
    )
