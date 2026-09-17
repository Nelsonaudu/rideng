from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import (
    Decimal,
    ROUND_HALF_UP,
)
from math import (
    asin,
    cos,
    radians,
    sin,
    sqrt,
)
from uuid import UUID

from app.models.trip_location_verification import (
    TripLocationVerificationState,
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


def _distance_meters(
    first_latitude: Decimal,
    first_longitude: Decimal,
    second_latitude: Decimal,
    second_longitude: Decimal,
) -> float:
    first_lat = radians(
        float(first_latitude)
    )

    first_lon = radians(
        float(first_longitude)
    )

    second_lat = radians(
        float(second_latitude)
    )

    second_lon = radians(
        float(second_longitude)
    )

    latitude_delta = (
        second_lat
        - first_lat
    )

    longitude_delta = (
        second_lon
        - first_lon
    )

    value = (
        sin(
            latitude_delta / 2
        )
        ** 2
        + cos(first_lat)
        * cos(second_lat)
        * sin(
            longitude_delta / 2
        )
        ** 2
    )

    return (
        2
        * 6371008.8
        * asin(
            sqrt(value)
        )
    )


def _decimal_2(
    value: float,
) -> Decimal:
    return Decimal(
        str(value)
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
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


def _is_exact_replay(
    *,
    state: TripLocationVerificationState,
    sample_id: UUID,
    latitude: Decimal,
    longitude: Decimal,
    horizontal_accuracy_m: Decimal,
    captured_at: datetime,
) -> bool:
    if (
        state.last_sample_id
        != sample_id
    ):
        return False

    if (
        state.last_latitude
        == latitude
        and state.last_longitude
        == longitude
        and state
        .last_horizontal_accuracy_m
        == horizontal_accuracy_m
        and state
        .last_sample_captured_at
        == captured_at
    ):
        return True

    raise LocationSampleConflictError(
        "Location sample ID was reused "
        "with different data."
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

    return (
        PickupLocationVerificationResult(
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
                state
                .arrival_candidate_count
            ),
            arrival_verified=(
                state.arrival_verified_at
                is not None
            ),
            arrival_newly_verified=False,
        )
    )


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

    if (
        captured_at.tzinfo is None
        or captured_at.utcoffset()
        is None
    ):
        raise (
            LocationSampleRejectedError(
                "Location timestamp must "
                "include a timezone."
            )
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

    if _is_exact_replay(
        state=state,
        sample_id=sample_id,
        latitude=latitude,
        longitude=longitude,
        horizontal_accuracy_m=(
            horizontal_accuracy_m
        ),
        captured_at=captured_at,
    ):
        return _replay_result(
            state=state,
        )

    if is_mocked is True:
        raise (
            LocationSampleRejectedError(
                "Mocked location samples "
                "cannot verify pickup."
            )
        )

    accuracy = float(
        horizontal_accuracy_m
    )

    if accuracy <= 0:
        raise (
            LocationSampleRejectedError(
                "Horizontal accuracy must "
                "be positive."
            )
        )

    if (
        accuracy
        > policy
        .max_horizontal_accuracy_m
    ):
        raise (
            LocationSampleRejectedError(
                "Location accuracy is "
                "too poor for pickup "
                "verification."
            )
        )

    age_seconds = (
        now
        - captured_at
    ).total_seconds()

    if (
        age_seconds
        > policy.max_sample_age_seconds
    ):
        raise (
            LocationSampleRejectedError(
                "Location sample is stale."
            )
        )

    if (
        age_seconds
        < -policy
        .max_future_skew_seconds
    ):
        raise (
            LocationSampleRejectedError(
                "Location timestamp is "
                "too far in the future."
            )
        )

    if (
        reported_speed_mps
        is not None
        and float(
            reported_speed_mps
        )
        > policy
        .max_plausible_speed_mps
    ):
        raise (
            LocationSampleRejectedError(
                "Reported vehicle speed "
                "is implausible."
            )
        )

    if (
        state.last_sample_captured_at
        is not None
        and captured_at
        <= state
        .last_sample_captured_at
    ):
        raise (
            LocationSampleSequenceError(
                "Location samples must "
                "have strictly increasing "
                "capture times."
            )
        )

    if (
        state.last_latitude
        is not None
        and state.last_longitude
        is not None
        and state
        .last_sample_captured_at
        is not None
    ):
        delta_seconds = (
            captured_at
            - state
            .last_sample_captured_at
        ).total_seconds()

        movement_m = (
            _distance_meters(
                state.last_latitude,
                state.last_longitude,
                latitude,
                longitude,
            )
        )

        if (
            delta_seconds > 0
            and (
                movement_m
                / delta_seconds
            )
            > policy
            .max_plausible_speed_mps
        ):
            raise (
                LocationSampleRejectedError(
                    "Location movement is "
                    "physically implausible."
                )
            )

    distance_to_pickup_m = (
        _distance_meters(
            latitude,
            longitude,
            pickup_latitude,
            pickup_longitude,
        )
    )

    progress_newly_verified = False
    arrival_newly_verified = False

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

    arrival_candidate = (
        distance_to_pickup_m
        + accuracy
        <= policy.arrival_radius_m
    )

    if (
        state.arrival_verified_at
        is None
    ):
        if arrival_candidate:
            if (
                state
                .arrival_candidate_count
                == 0
                or state
                .last_arrival_candidate_at
                is None
            ):
                state.arrival_candidate_count = (
                    1
                )

                state.last_arrival_candidate_at = (
                    captured_at
                )

            else:
                candidate_delta_seconds = (
                    captured_at
                    - state
                    .last_arrival_candidate_at
                ).total_seconds()

                if (
                    candidate_delta_seconds
                    < policy
                    .min_arrival_sample_separation_seconds
                ):
                    pass

                elif (
                    candidate_delta_seconds
                    <= policy
                    .max_arrival_sample_separation_seconds
                ):
                    state.arrival_candidate_count += (
                        1
                    )

                    state.last_arrival_candidate_at = (
                        captured_at
                    )

                else:
                    state.arrival_candidate_count = (
                        1
                    )

                    state.last_arrival_candidate_at = (
                        captured_at
                    )

            if (
                state
                .arrival_candidate_count
                >= 2
            ):
                state.arrival_verified_at = (
                    now
                )

                arrival_newly_verified = (
                    True
                )

                if (
                    state
                    .progress_verified_at
                    is None
                ):
                    state.progress_verified_at = (
                        now
                    )

                    progress_newly_verified = (
                        True
                    )

        else:
            state.arrival_candidate_count = (
                0
            )

            state.last_arrival_candidate_at = (
                None
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

    return (
        PickupLocationVerificationResult(
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
                state
                .arrival_candidate_count
            ),
            arrival_verified=(
                state.arrival_verified_at
                is not None
            ),
            arrival_newly_verified=(
                arrival_newly_verified
            ),
        )
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