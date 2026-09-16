from uuid import UUID

from sqlalchemy.orm import Session

from app.models.ride_request import (
    RideRequest,
)
from app.models.rider_profile import (
    RiderProfile,
)
from app.models.trip_event import (
    TripEvent,
)
from app.models.trip_stop import (
    TripStop,
)
from app.schemas.rides import (
    RideRequestCreate,
)
from app.services.ride_policy import (
    FareBand,
    build_development_fare_band,
)


class RiderProfileRequiredError(
    ValueError
):
    pass


class RideFareValidationError(
    ValueError
):
    pass


def quote_ride_request(
    *,
    payload: RideRequestCreate,
) -> FareBand:
    points = [
        (
            payload.pickup.latitude,
            payload.pickup.longitude,
        ),
    ]

    points.extend(
        (
            stop.latitude,
            stop.longitude,
        )
        for stop
        in payload.planned_stops
    )

    points.append(
        (
            payload.destination.latitude,
            payload.destination.longitude,
        )
    )

    return (
        build_development_fare_band(
            points=points,
        )
    )


def validate_requested_fare(
    *,
    payload: RideRequestCreate,
    fare_band: FareBand,
) -> None:
    if (
        payload.ride_mode
        == "quick_ride"
    ):
        return

    rider_offer = (
        payload.rider_offer_fare
    )

    if rider_offer is None:
        raise RideFareValidationError(
            "Negotiated ride requires "
            "a rider offer."
        )

    if (
        rider_offer
        < fare_band.minimum_offer_fare
    ):
        raise RideFareValidationError(
            "Rider offer is below the "
            "minimum accepted fare."
        )

    if (
        rider_offer
        > fare_band.maximum_counteroffer_fare
    ):
        raise RideFareValidationError(
            "Rider offer exceeds the "
            "maximum permitted fare."
        )


def create_ride_request(
    *,
    db: Session,
    rider_id: UUID,
    payload: RideRequestCreate,
) -> RideRequest:
    rider_profile = db.get(
        RiderProfile,
        rider_id,
    )

    if rider_profile is None:
        raise RiderProfileRequiredError(
            "Rider profile is required."
        )

    fare_band = quote_ride_request(
        payload=payload,
    )

    validate_requested_fare(
        payload=payload,
        fare_band=fare_band,
    )

    ride_request = RideRequest(
        rider_id=rider_id,
        ride_mode=payload.ride_mode,
        status="searching",
        payment_method=(
            payload.payment_method
        ),
        pickup_address=(
            payload.pickup.address
        ),
        pickup_latitude=(
            payload.pickup.latitude
        ),
        pickup_longitude=(
            payload.pickup.longitude
        ),
        destination_address=(
            payload.destination.address
        ),
        destination_latitude=(
            payload.destination.latitude
        ),
        destination_longitude=(
            payload.destination.longitude
        ),
        recommended_fare=(
            fare_band.recommended_fare
        ),
        minimum_offer_fare=(
            fare_band.minimum_offer_fare
        ),
        quick_ride_fare=(
            fare_band.quick_ride_fare
        ),
        maximum_counteroffer_fare=(
            fare_band
            .maximum_counteroffer_fare
        ),
        rider_offer_fare=(
            payload.rider_offer_fare
        ),
    )

    try:
        db.add(
            ride_request
        )

        db.flush()

        stops: list[
            TripStop
        ] = []

        stops.append(
            TripStop(
                ride_request_id=(
                    ride_request.id
                ),
                trip_id=None,
                sequence=0,
                stop_type="pickup",
                address=(
                    payload.pickup.address
                ),
                latitude=(
                    payload.pickup.latitude
                ),
                longitude=(
                    payload.pickup.longitude
                ),
                planned_before_matching=True,
            )
        )

        for (
            index,
            stop,
        ) in enumerate(
            payload.planned_stops,
            start=1,
        ):
            stops.append(
                TripStop(
                    ride_request_id=(
                        ride_request.id
                    ),
                    trip_id=None,
                    sequence=index,
                    stop_type=(
                        "intermediate"
                    ),
                    address=(
                        stop.address
                    ),
                    latitude=(
                        stop.latitude
                    ),
                    longitude=(
                        stop.longitude
                    ),
                    planned_before_matching=True,
                )
            )

        stops.append(
            TripStop(
                ride_request_id=(
                    ride_request.id
                ),
                trip_id=None,
                sequence=(
                    len(
                        payload
                        .planned_stops
                    )
                    + 1
                ),
                stop_type="destination",
                address=(
                    payload
                    .destination
                    .address
                ),
                latitude=(
                    payload
                    .destination
                    .latitude
                ),
                longitude=(
                    payload
                    .destination
                    .longitude
                ),
                planned_before_matching=True,
            )
        )

        db.add_all(
            stops
        )

        db.add(
            TripEvent(
                ride_request_id=(
                    ride_request.id
                ),
                trip_id=None,
                actor_user_id=rider_id,
                event_type=(
                    "ride_requested"
                ),
                event_data={
                    "ride_mode": (
                        payload.ride_mode
                    ),
                    "payment_method": (
                        payload
                        .payment_method
                    ),
                    "intermediate_stop_count": (
                        len(
                            payload
                            .planned_stops
                        )
                    ),
                },
            )
        )

        db.commit()

        db.refresh(
            ride_request
        )

        return ride_request

    except Exception:
        db.rollback()
        raise