from fastapi import APIRouter

from app.api.routes import auth, drivers, health, users, vehicles


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