from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import asin, cos, radians, sin, sqrt
from collections.abc import Sequence


MONEY_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class RideTimingPolicy:
    quick_driver_seconds: int
    negotiation_driver_seconds: int
    rider_selection_seconds: int

    free_cancel_seconds: int
    arrival_free_wait_seconds: int

    stop_free_wait_seconds: int
    stop_control_seconds: int
    stop_extension_seconds: int

    maximum_intermediate_stops: int


@dataclass(frozen=True)
class RideFarePolicy:
    base_fare: Decimal
    per_km_fare: Decimal
    minimum_recommended_fare: Decimal

    minimum_offer_ratio: Decimal
    quick_priority_ratio: Decimal
    maximum_counter_ratio: Decimal


@dataclass(frozen=True)
class FareBand:
    minimum_offer_fare: Decimal
    recommended_fare: Decimal
    quick_ride_fare: Decimal
    maximum_counteroffer_fare: Decimal


ABUJA_RIDE_TIMING_POLICY = RideTimingPolicy(
    quick_driver_seconds=10,
    negotiation_driver_seconds=25,
    rider_selection_seconds=30,
    free_cancel_seconds=120,
    arrival_free_wait_seconds=300,
    stop_free_wait_seconds=180,
    stop_control_seconds=600,
    stop_extension_seconds=300,
    maximum_intermediate_stops=4,
)


ABUJA_DEVELOPMENT_FARE_POLICY = RideFarePolicy(
    base_fare=Decimal("1200.00"),
    per_km_fare=Decimal("350.00"),
    minimum_recommended_fare=Decimal("1800.00"),
    minimum_offer_ratio=Decimal("0.80"),
    quick_priority_ratio=Decimal("1.15"),
    maximum_counter_ratio=Decimal("1.35"),
)


def _money(
    amount: Decimal,
) -> Decimal:
    return amount.quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def build_fare_band(
    *,
    recommended_fare: Decimal,
    minimum_offer_ratio: Decimal,
    quick_priority_ratio: Decimal,
    maximum_counter_ratio: Decimal,
) -> FareBand:
    if recommended_fare <= 0:
        raise ValueError(
            "Recommended fare must be positive."
        )

    if not (
        Decimal("0")
        < minimum_offer_ratio
        < Decimal("1")
    ):
        raise ValueError(
            "Minimum offer ratio must be "
            "greater than 0 and less than 1."
        )

    if quick_priority_ratio <= Decimal("1"):
        raise ValueError(
            "Quick Ride priority ratio must be "
            "greater than 1."
        )

    if maximum_counter_ratio <= Decimal("1"):
        raise ValueError(
            "Maximum counter ratio must be "
            "greater than 1."
        )

    minimum_offer = _money(
        recommended_fare
        * minimum_offer_ratio
    )

    recommended = _money(
        recommended_fare
    )

    quick_ride = _money(
        recommended_fare
        * quick_priority_ratio
    )

    maximum_counter = _money(
        recommended_fare
        * maximum_counter_ratio
    )

    if maximum_counter <= minimum_offer:
        raise ValueError(
            "Maximum counteroffer must exceed "
            "minimum offer."
        )

    return FareBand(
        minimum_offer_fare=minimum_offer,
        recommended_fare=recommended,
        quick_ride_fare=quick_ride,
        maximum_counteroffer_fare=maximum_counter,
    )


def _haversine_km(
    first: tuple[Decimal, Decimal],
    second: tuple[Decimal, Decimal],
) -> Decimal:
    first_latitude = radians(
        float(first[0])
    )

    first_longitude = radians(
        float(first[1])
    )

    second_latitude = radians(
        float(second[0])
    )

    second_longitude = radians(
        float(second[1])
    )

    latitude_delta = (
        second_latitude
        - first_latitude
    )

    longitude_delta = (
        second_longitude
        - first_longitude
    )

    value = (
        sin(latitude_delta / 2) ** 2
        + cos(first_latitude)
        * cos(second_latitude)
        * sin(longitude_delta / 2) ** 2
    )

    distance = (
        2
        * 6371.0088
        * asin(sqrt(value))
    )

    return Decimal(
        str(distance)
    )


def estimate_route_distance_km(
    *,
    points: Sequence[
        tuple[Decimal, Decimal]
    ],
) -> Decimal:
    if len(points) < 2:
        raise ValueError(
            "At least two route points are required."
        )

    total = Decimal("0")

    for index in range(
        len(points) - 1
    ):
        total += _haversine_km(
            points[index],
            points[index + 1],
        )

    return total


def build_development_fare_band(
    *,
    points: Sequence[
        tuple[Decimal, Decimal]
    ],
    policy: RideFarePolicy = (
        ABUJA_DEVELOPMENT_FARE_POLICY
    ),
) -> FareBand:
    distance_km = (
        estimate_route_distance_km(
            points=points,
        )
    )

    estimated_fare = (
        policy.base_fare
        + (
            distance_km
            * policy.per_km_fare
        )
    )

    recommended_fare = max(
        estimated_fare,
        policy.minimum_recommended_fare,
    )

    return build_fare_band(
        recommended_fare=(
            recommended_fare
        ),
        minimum_offer_ratio=(
            policy.minimum_offer_ratio
        ),
        quick_priority_ratio=(
            policy.quick_priority_ratio
        ),
        maximum_counter_ratio=(
            policy.maximum_counter_ratio
        ),
    )