from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class RideLocation(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    address: str = Field(
        min_length=1,
        max_length=500,
    )

    latitude: Decimal = Field(
        ge=Decimal("-90"),
        le=Decimal("90"),
    )

    longitude: Decimal = Field(
        ge=Decimal("-180"),
        le=Decimal("180"),
    )


class RideRequestCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    ride_mode: Literal[
        "quick_ride",
        "negotiate",
    ]

    payment_method: Literal[
        "cash",
        "electronic",
    ]

    pickup: RideLocation
    destination: RideLocation

    planned_stops: list[
        RideLocation
    ] = Field(
        default_factory=list,
        max_length=4,
    )

    rider_offer_fare: (
        Decimal | None
    ) = Field(
        default=None,
        gt=Decimal("0"),
    )

    @model_validator(
        mode="after"
    )
    def validate_ride_mode(
        self,
    ):
        if (
            self.ride_mode
            == "quick_ride"
            and self.rider_offer_fare
            is not None
        ):
            raise ValueError(
                "Quick Ride does not accept "
                "a rider offer."
            )

        if (
            self.ride_mode
            == "negotiate"
            and self.rider_offer_fare
            is None
        ):
            raise ValueError(
                "Negotiated rides require "
                "a rider offer."
            )

        return self


class RideRequestResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: UUID
    rider_id: UUID

    ride_mode: str
    status: str
    payment_method: str

    pickup_address: str
    pickup_latitude: Decimal
    pickup_longitude: Decimal

    destination_address: str
    destination_latitude: Decimal
    destination_longitude: Decimal

    recommended_fare: Decimal
    minimum_offer_fare: Decimal
    quick_ride_fare: Decimal
    maximum_counteroffer_fare: Decimal

    rider_offer_fare: (
        Decimal | None
    )

    matched_fare: (
        Decimal | None
    )

    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None