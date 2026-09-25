from fastapi import APIRouter

from app.api.routes import (
    auth,
    drivers,
    health,
    pickup_location,
    ride_cancellation,
    rides,
    trip_verification,
    trip_stops,
    trips,
    users,
    vehicles,
)


api_router = APIRouter()


api_router.include_router(
    health.router,
    tags=["Health"],
)


api_router.include_router(
    auth.router,
    tags=["Authentication"],
)


api_router.include_router(
    users.router,
    tags=["Users"],
)


api_router.include_router(
    drivers.router,
    tags=["Drivers"],
)


api_router.include_router(
    vehicles.router,
    tags=["Vehicles"],
)


api_router.include_router(
    rides.router,
    tags=["Rides"],
)


api_router.include_router(
    rides.offer_router,
    tags=["Ride Offers"],
)


api_router.include_router(
    trips.router,
    tags=["Trips"],
)


api_router.include_router(
    trip_verification.router,
    tags=["Trip Verification"],
)


api_router.include_router(
    trip_stops.router,
    tags=["Trip Stops"],
)


api_router.include_router(
    pickup_location.router,
    tags=[
        "Pickup Location Verification"
    ],
)


api_router.include_router(
    ride_cancellation.ride_router,
    tags=["Ride Cancellation"],
)


api_router.include_router(
    ride_cancellation.trip_router,
    tags=[
        "Trip Cancellation and No-Show"
    ],
)