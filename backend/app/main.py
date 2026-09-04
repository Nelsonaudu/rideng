from fastapi import FastAPI


app = FastAPI(
    title="RideNG API",
    description="Backend API for the RideNG ride-hailing platform.",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "message": "Welcome to RideNG",
        "pilot_city": "Abuja",
        "country": "Nigeria",
    }


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "rideng-api",
    }