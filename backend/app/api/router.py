from fastapi import APIRouter

from app.api.routes import drivers, health, users


api_router = APIRouter()

api_router.include_router(
    health.router,
    tags=["Health"],
)

api_router.include_router(
    users.router,
    tags=["Users"],
)

api_router.include_router(
    drivers.router,
    tags=["Drivers"],
)