from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt
from uuid import UUID


@dataclass(frozen=True)
class ArrivalLocationPolicy:
    arrival_radius_m: float
    max_horizontal_accuracy_m: float

    max_sample_age_seconds: int
    max_future_skew_seconds: int

    min_confirmation_separation_seconds: int
    max_confirmation_separation_seconds: int

    max_plausible_speed_mps: float


@dataclass(frozen=True)
class LocationSample:
    sample_id: UUID

    latitude: Decimal
    longitude: Decimal

    horizontal_accuracy_m: Decimal
    captured_at: datetime

    reported_speed_mps: Decimal | None = None
    is_mocked: bool | None = None


@dataclass(frozen=True)
class LocationValidationResult:
    replayed: bool
    distance_to_target_m: float


@dataclass(frozen=True)
class ArrivalConfirmationResult:
    candidate_count: int
    last_candidate_at: datetime | None

    arrival_verified: bool
    arrival_newly_verified: bool


class LocationVerificationError(
    ValueError
):
    pass


class LocationSampleRejectedError(
    LocationVerificationError
):
    pass


class LocationSampleSequenceError(
    LocationVerificationError
):
    pass


class LocationSampleConflictError(
    LocationVerificationError
):
    pass


def distance_meters(
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


def _same_sample_data(
    *,
    first: LocationSample,
    second: LocationSample,
) -> bool:
    return bool(
        first.sample_id
        == second.sample_id
        and first.latitude
        == second.latitude
        and first.longitude
        == second.longitude
        and first.horizontal_accuracy_m
        == second.horizontal_accuracy_m
        and first.captured_at
        == second.captured_at
        and first.reported_speed_mps
        == second.reported_speed_mps
        and first.is_mocked
        == second.is_mocked
    )


def _check_replay(
    *,
    sample: LocationSample,
    previous_sample: LocationSample | None,
) -> bool:
    if previous_sample is None:
        return False

    if (
        previous_sample.sample_id
        != sample.sample_id
    ):
        return False

    if _same_sample_data(
        first=sample,
        second=previous_sample,
    ):
        return True

    raise LocationSampleConflictError(
        "Location sample ID was reused "
        "with different data."
    )


def validate_location_sample(
    *,
    sample: LocationSample,
    target_latitude: Decimal,
    target_longitude: Decimal,
    previous_sample: LocationSample | None,
    now: datetime,
    policy: ArrivalLocationPolicy,
) -> LocationValidationResult:
    replayed = _check_replay(
        sample=sample,
        previous_sample=previous_sample,
    )

    if replayed:
        return LocationValidationResult(
            replayed=True,
            distance_to_target_m=(
                distance_meters(
                    sample.latitude,
                    sample.longitude,
                    target_latitude,
                    target_longitude,
                )
            ),
        )

    if (
        sample.captured_at.tzinfo is None
        or sample.captured_at.utcoffset()
        is None
    ):
        raise LocationSampleRejectedError(
            "Location timestamp must "
            "include a timezone."
        )

    if sample.is_mocked is True:
        raise LocationSampleRejectedError(
            "Mocked location samples "
            "cannot verify arrival."
        )

    accuracy = float(
        sample.horizontal_accuracy_m
    )

    if accuracy <= 0:
        raise LocationSampleRejectedError(
            "Horizontal accuracy must "
            "be positive."
        )

    if (
        accuracy
        > policy.max_horizontal_accuracy_m
    ):
        raise LocationSampleRejectedError(
            "Location accuracy is "
            "too poor for verification."
        )

    age_seconds = (
        now
        - sample.captured_at
    ).total_seconds()

    if (
        age_seconds
        > policy.max_sample_age_seconds
    ):
        raise LocationSampleRejectedError(
            "Location sample is stale."
        )

    if (
        age_seconds
        < -policy.max_future_skew_seconds
    ):
        raise LocationSampleRejectedError(
            "Location timestamp is "
            "too far in the future."
        )

    if (
        sample.reported_speed_mps
        is not None
        and float(
            sample.reported_speed_mps
        )
        > policy.max_plausible_speed_mps
    ):
        raise LocationSampleRejectedError(
            "Reported vehicle speed "
            "is implausible."
        )

    if previous_sample is not None:
        if (
            sample.captured_at
            <= previous_sample.captured_at
        ):
            raise LocationSampleSequenceError(
                "Location samples must "
                "have strictly increasing "
                "capture times."
            )

        delta_seconds = (
            sample.captured_at
            - previous_sample.captured_at
        ).total_seconds()

        movement_m = distance_meters(
            previous_sample.latitude,
            previous_sample.longitude,
            sample.latitude,
            sample.longitude,
        )

        if (
            delta_seconds > 0
            and (
                movement_m
                / delta_seconds
            )
            > policy.max_plausible_speed_mps
        ):
            raise LocationSampleRejectedError(
                "Location movement is "
                "physically implausible."
            )

    distance_to_target_m = (
        distance_meters(
            sample.latitude,
            sample.longitude,
            target_latitude,
            target_longitude,
        )
    )

    return LocationValidationResult(
        replayed=False,
        distance_to_target_m=(
            distance_to_target_m
        ),
    )


def advance_arrival_confirmation(
    *,
    candidate_count: int,
    last_candidate_at: datetime | None,
    already_verified: bool,
    distance_to_target_m: float,
    horizontal_accuracy_m: Decimal,
    captured_at: datetime,
    policy: ArrivalLocationPolicy,
) -> ArrivalConfirmationResult:
    if candidate_count < 0:
        raise ValueError(
            "Candidate count cannot "
            "be negative."
        )

    if already_verified:
        return ArrivalConfirmationResult(
            candidate_count=candidate_count,
            last_candidate_at=(
                last_candidate_at
            ),
            arrival_verified=True,
            arrival_newly_verified=False,
        )

    arrival_candidate = (
        distance_to_target_m
        + float(
            horizontal_accuracy_m
        )
        <= policy.arrival_radius_m
    )

    if not arrival_candidate:
        return ArrivalConfirmationResult(
            candidate_count=0,
            last_candidate_at=None,
            arrival_verified=False,
            arrival_newly_verified=False,
        )

    if (
        candidate_count == 0
        or last_candidate_at is None
    ):
        return ArrivalConfirmationResult(
            candidate_count=1,
            last_candidate_at=captured_at,
            arrival_verified=False,
            arrival_newly_verified=False,
        )

    candidate_delta_seconds = (
        captured_at
        - last_candidate_at
    ).total_seconds()

    if (
        candidate_delta_seconds
        < policy.min_confirmation_separation_seconds
    ):
        return ArrivalConfirmationResult(
            candidate_count=candidate_count,
            last_candidate_at=(
                last_candidate_at
            ),
            arrival_verified=False,
            arrival_newly_verified=False,
        )

    if (
        candidate_delta_seconds
        > policy.max_confirmation_separation_seconds
    ):
        return ArrivalConfirmationResult(
            candidate_count=1,
            last_candidate_at=captured_at,
            arrival_verified=False,
            arrival_newly_verified=False,
        )

    next_candidate_count = (
        candidate_count + 1
    )

    newly_verified = (
        next_candidate_count >= 2
    )

    return ArrivalConfirmationResult(
        candidate_count=(
            next_candidate_count
        ),
        last_candidate_at=captured_at,
        arrival_verified=(
            newly_verified
        ),
        arrival_newly_verified=(
            newly_verified
        ),
    )
