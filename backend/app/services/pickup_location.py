from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import (
    Decimal,
    ROUND_HALF_UP,
)
from uuid import UUID

from app.models.trip_location_verification import (
    TripLocationVerificationState,
)
from app.services.location_verification import (
    ArrivalLocationPolicy,
    LocationSample,
    LocationSampleConflictError as GenericLocationSampleConflictError,
    LocationSampleRejectedError as GenericLocationSampleRejectedError,
    LocationSampleSequenceError as GenericLocationSampleSequenceError,
    advance_arrival_confirmation,
    validate_location_sample,
)


@dataclass(frozen=True)
class PickupLocationVerificationPolicy:
    arrival_radius_m: float
    max_horizontal_accuracy_m: float

    max_sample_age_seconds: int
    max_future_skew_seconds: int

    min_arrival_sample_separation_seconds: int
    max_arrival_sample_separation_seconds: int

    min_progress_sample_separation_seconds: int
    max_progress_window_seconds: int
    min_progress_reduction_m: float

    max_plausible_speed_mps: float


@dataclass(frozen=True)
class PickupLocationVerificationResult:
    replayed: bool

    distance_to_pickup_m: float

    progress_verified: bool
    progress_newly_verified: bool

    arrival_candidate_count: int

    arrival_verified: bool
    arrival_newly_verified: bool


ABUJA_PICKUP_LOCATION_POLICY = (
    PickupLocationVerificationPolicy(
        arrival_radius_m=100.0,
        max_horizontal_accuracy_m=50.0,
        max_sample_age_seconds=15,
        max_future_skew_seconds=5,
        min_arrival_sample_separation_seconds=3,
        max_arrival_sample_separation_seconds=10,
        min_progress_sample_separation_seconds=5,
        max_progress_window_seconds=180,
        min_progress_reduction_m=50.0,
        max_plausible_speed_mps=55.0,
    )
)


class PickupLocationVerificationError(
    ValueError
):
    pass


class LocationSampleRejectedError(
    PickupLocationVerificationError
):
    pass


class LocationSampleSequenceError(
    PickupLocationVerificationError
):
    pass


class LocationSampleConflictError(
    PickupLocationVerificationError
):
    pass


def _decimal_2(
    value: float,
) -> Decimal:
    return Decimal(
        str(value)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _arrival_policy(
    *,
    policy: PickupLocationVerificationPolicy,
) -> ArrivalLocationPolicy:
    return ArrivalLocationPolicy(
        arrival_radius_m=(
            policy.arrival_radius_m
        ),
        max_horizontal_accuracy_m=(
            policy.max_horizontal_accuracy_m
        ),
        max_sample_age_seconds=(
            policy.max_sample_age_seconds
        ),
        max_future_skew_seconds=(
            policy.max_future_skew_seconds
        ),
        min_confirmation_separation_seconds=(
            policy
            .min_arrival_sample_separation_seconds
        ),
        max_confirmation_separation_seconds=(
            policy
            .max_arrival_sample_separation_seconds
        ),
        max_plausible_speed_mps=(
            policy.max_plausible_speed_mps
        ),
    )


def _reset_for_assignment(
    *,
    state: TripLocationVerificationState,
    assignment_id: UUID,
    now: datetime,
) -> None:
    state.assignment_id = (
        assignment_id
    )

    state.last_sample_id = None
    state.last_latitude = None
    state.last_longitude = None
    state.last_horizontal_accuracy_m = None
    state.last_distance_to_pickup_m = None
    state.last_sample_captured_at = None
    state.last_sample_received_at = None

    state.progress_anchor_distance_to_pickup_m = (
        None
    )

    state.progress_anchor_horizontal_accuracy_m = (
        None
    )

    state.progress_anchor_captured_at = None

    state.arrival_candidate_count = 0
    state.last_arrival_candidate_at = None

    state.progress_verified_at = None
    state.arrival_verified_at = None

    state.updated_at = now


def _stored_previous_sample(
    *,
    state: TripLocationVerificationState,
    reported_speed_mps: Decimal | None,
    is_mocked: bool | None,
) -> LocationSample | None:
    required_values = (
        state.last_sample_id,
        state.last_latitude,
        state.last_longitude,
        state.last_horizontal_accuracy_m,
        state.last_sample_captured_at,
    )

    if any(
        value is None
        for value in required_values
    ):
        return None

    return LocationSample(
        sample_id=state.last_sample_id,
        latitude=state.last_latitude,
        longitude=state.last_longitude,
        horizontal_accuracy_m=(
            state.last_horizontal_accuracy_m
        ),
        captured_at=(
            state.last_sample_captured_at
        ),
        # These two values are not persisted in
        # the Batch 8 rolling state. Supplying the
        # current values preserves Batch 8 replay
        # identity semantics, which were based on
        # the persisted fields above.
        reported_speed_mps=(
            reported_speed_mps
        ),
        is_mocked=is_mocked,
    )


def _replay_result(
    *,
    state: TripLocationVerificationState,
) -> PickupLocationVerificationResult:
    if (
        state.last_distance_to_pickup_m
        is None
    ):
        raise LocationSampleConflictError(
            "Stored location sample "
            "is incomplete."
        )

    return PickupLocationVerificationResult(
        replayed=True,
        distance_to_pickup_m=float(
            state
            .last_distance_to_pickup_m
        ),
        progress_verified=(
            state.progress_verified_at
            is not None
        ),
        progress_newly_verified=False,
        arrival_candidate_count=(
            state.arrival_candidate_count
        ),
        arrival_verified=(
            state.arrival_verified_at
            is not None
        ),
        arrival_newly_verified=False,
    )


def _validate_with_shared_engine(
    *,
    sample: LocationSample,
    previous_sample: LocationSample | None,
    pickup_latitude: Decimal,
    pickup_longitude: Decimal,
    now: datetime,
    policy: PickupLocationVerificationPolicy,
):
    try:
        return validate_location_sample(
            sample=sample,
            target_latitude=pickup_latitude,
            target_longitude=pickup_longitude,
            previous_sample=previous_sample,
            now=now,
            policy=_arrival_policy(
                policy=policy,
            ),
        )

    except GenericLocationSampleRejectedError as exc:
        raise LocationSampleRejectedError(
            str(exc)
        ) from exc

    except GenericLocationSampleSequenceError as exc:
        raise LocationSampleSequenceError(
            str(exc)
        ) from exc

    except GenericLocationSampleConflictError as exc:
        raise LocationSampleConflictError(
            str(exc)
        ) from exc


def process_pickup_location_observation(
    *,
    state: TripLocationVerificationState,
    assignment_id: UUID,
    pickup_latitude: Decimal,
    pickup_longitude: Decimal,
    sample_id: UUID,
    latitude: Decimal,
    longitude: Decimal,
    horizontal_accuracy_m: Decimal,
    captured_at: datetime,
    reported_speed_mps: (
        Decimal | None
    ) = None,
    is_mocked: bool | None = None,
    now: datetime | None = None,
    policy: PickupLocationVerificationPolicy = (
        ABUJA_PICKUP_LOCATION_POLICY
    ),
) -> PickupLocationVerificationResult:
    now = (
        now
        or datetime.now(UTC)
    )

    # Preserve the original Batch 8 behavior:
    # a malformed timezone does not mutate
    # assignment-scoped verification state.
    if (
        captured_at.tzinfo is None
        or captured_at.utcoffset()
        is None
    ):
        raise LocationSampleRejectedError(
            "Location timestamp must "
            "include a timezone."
        )

    if (
        state.assignment_id
        != assignment_id
    ):
        _reset_for_assignment(
            state=state,
            assignment_id=assignment_id,
            now=now,
        )

    sample = LocationSample(
        sample_id=sample_id,
        latitude=latitude,
        longitude=longitude,
        horizontal_accuracy_m=(
            horizontal_accuracy_m
        ),
        captured_at=captured_at,
        reported_speed_mps=(
            reported_speed_mps
        ),
        is_mocked=is_mocked,
    )

    previous_sample = (
        _stored_previous_sample(
            state=state,
            reported_speed_mps=(
                reported_speed_mps
            ),
            is_mocked=is_mocked,
        )
    )

    if (
        state.last_sample_id
        == sample_id
        and previous_sample is None
    ):
        raise LocationSampleConflictError(
            "Stored location sample "
            "is incomplete."
        )

    validation = (
        _validate_with_shared_engine(
            sample=sample,
            previous_sample=previous_sample,
            pickup_latitude=(
                pickup_latitude
            ),
            pickup_longitude=(
                pickup_longitude
            ),
            now=now,
            policy=policy,
        )
    )

    if validation.replayed:
        return _replay_result(
            state=state,
        )

    distance_to_pickup_m = (
        validation.distance_to_target_m
    )

    accuracy = float(
        horizontal_accuracy_m
    )

    progress_newly_verified = False

    if (
        state.progress_verified_at
        is None
    ):
        if (
            state
            .progress_anchor_distance_to_pickup_m
            is None
            or state
            .progress_anchor_horizontal_accuracy_m
            is None
            or state
            .progress_anchor_captured_at
            is None
        ):
            state.progress_anchor_distance_to_pickup_m = (
                _decimal_2(
                    distance_to_pickup_m
                )
            )

            state.progress_anchor_horizontal_accuracy_m = (
                horizontal_accuracy_m
            )

            state.progress_anchor_captured_at = (
                captured_at
            )

        else:
            anchor_age_seconds = (
                captured_at
                - state
                .progress_anchor_captured_at
            ).total_seconds()

            anchor_distance = float(
                state
                .progress_anchor_distance_to_pickup_m
            )

            anchor_accuracy = float(
                state
                .progress_anchor_horizontal_accuracy_m
            )

            if (
                anchor_age_seconds
                > policy
                .max_progress_window_seconds
            ):
                state.progress_anchor_distance_to_pickup_m = (
                    _decimal_2(
                        distance_to_pickup_m
                    )
                )

                state.progress_anchor_horizontal_accuracy_m = (
                    horizontal_accuracy_m
                )

                state.progress_anchor_captured_at = (
                    captured_at
                )

            elif (
                anchor_age_seconds
                >= policy
                .min_progress_sample_separation_seconds
            ):
                conservative_reduction = (
                    (
                        anchor_distance
                        - anchor_accuracy
                    )
                    - (
                        distance_to_pickup_m
                        + accuracy
                    )
                )

                if (
                    conservative_reduction
                    >= policy
                    .min_progress_reduction_m
                ):
                    state.progress_verified_at = (
                        now
                    )

                    progress_newly_verified = (
                        True
                    )

                elif (
                    distance_to_pickup_m
                    > (
                        anchor_distance
                        + anchor_accuracy
                        + accuracy
                    )
                ):
                    state.progress_anchor_distance_to_pickup_m = (
                        _decimal_2(
                            distance_to_pickup_m
                        )
                    )

                    state.progress_anchor_horizontal_accuracy_m = (
                        horizontal_accuracy_m
                    )

                    state.progress_anchor_captured_at = (
                        captured_at
                    )

    confirmation = (
        advance_arrival_confirmation(
            candidate_count=(
                state.arrival_candidate_count
            ),
            last_candidate_at=(
                state.last_arrival_candidate_at
            ),
            already_verified=(
                state.arrival_verified_at
                is not None
            ),
            distance_to_target_m=(
                distance_to_pickup_m
            ),
            horizontal_accuracy_m=(
                horizontal_accuracy_m
            ),
            captured_at=captured_at,
            policy=_arrival_policy(
                policy=policy,
            ),
        )
    )

    state.arrival_candidate_count = (
        confirmation.candidate_count
    )

    state.last_arrival_candidate_at = (
        confirmation.last_candidate_at
    )

    arrival_newly_verified = (
        confirmation
        .arrival_newly_verified
    )

    if arrival_newly_verified:
        state.arrival_verified_at = (
            now
        )

        if (
            state.progress_verified_at
            is None
        ):
            state.progress_verified_at = (
                now
            )

            progress_newly_verified = (
                True
            )

    state.last_sample_id = (
        sample_id
    )

    state.last_latitude = (
        latitude
    )

    state.last_longitude = (
        longitude
    )

    state.last_horizontal_accuracy_m = (
        horizontal_accuracy_m
    )

    state.last_distance_to_pickup_m = (
        _decimal_2(
            distance_to_pickup_m
        )
    )

    state.last_sample_captured_at = (
        captured_at
    )

    state.last_sample_received_at = (
        now
    )

    state.updated_at = now

    return PickupLocationVerificationResult(
        replayed=False,
        distance_to_pickup_m=(
            distance_to_pickup_m
        ),
        progress_verified=(
            state.progress_verified_at
            is not None
        ),
        progress_newly_verified=(
            progress_newly_verified
        ),
        arrival_candidate_count=(
            state.arrival_candidate_count
        ),
        arrival_verified=(
            state.arrival_verified_at
            is not None
        ),
        arrival_newly_verified=(
            arrival_newly_verified
        ),
    )


def has_verified_pickup_progress(
    *,
    state: (
        TripLocationVerificationState
        | None
    ),
    assignment_id: UUID,
) -> bool:
    return bool(
        state is not None
        and state.assignment_id
        == assignment_id
        and state.progress_verified_at
        is not None
    )


def has_verified_pickup_arrival(
    *,
    state: (
        TripLocationVerificationState
        | None
    ),
    assignment_id: UUID,
) -> bool:
    return bool(
        state is not None
        and state.assignment_id
        == assignment_id
        and state.arrival_verified_at
        is not None
    )


def redact_transient_location_state(
    *,
    state: (
        TripLocationVerificationState
        | None
    ),
    now: datetime | None = None,
) -> None:
    if state is None:
        return

    state.last_sample_id = None

    state.last_latitude = None
    state.last_longitude = None

    state.last_horizontal_accuracy_m = (
        None
    )

    state.last_distance_to_pickup_m = (
        None
    )

    state.last_sample_captured_at = (
        None
    )

    state.last_sample_received_at = (
        None
    )

    state.progress_anchor_distance_to_pickup_m = (
        None
    )

    state.progress_anchor_horizontal_accuracy_m = (
        None
    )

    state.progress_anchor_captured_at = (
        None
    )

    state.arrival_candidate_count = 0

    state.last_arrival_candidate_at = (
        None
    )

    state.updated_at = (
        now
        or datetime.now(UTC)
    )


def redact_location_for_assignment(
    *,
    state: (
        TripLocationVerificationState
        | None
    ),
    assignment_id: UUID,
    now: datetime | None = None,
) -> bool:
    if state is None:
        return False

    if (
        state.assignment_id
        != assignment_id
    ):
        return False

    redact_transient_location_state(
        state=state,
        now=now,
    )

    return True