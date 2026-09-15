from fastapi import FastAPI

from app.api.router import api_router
from app.api.routes.compliance import router as compliance_router
from app.api.routes.readiness import router as readiness_router
from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    description="Backend API for the RideNG ride-hailing platform.",
    version=settings.app_version,
)


@app.get("/")
def root():
    return {
        "message": "Welcome to RideNG",
        "pilot_city": settings.pilot_city,
        "country": settings.country,
        "currency": settings.currency,
        "environment": settings.environment,
    }


app.include_router(
    api_router,
    prefix=settings.api_v1_prefix,
)

app.include_router(
    compliance_router,
)

app.include_router(
    readiness_router,
)