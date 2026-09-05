from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RideNG API"
    app_version: str = "0.2.0"
    environment: str = "development"

    api_v1_prefix: str = "/api/v1"

    pilot_city: str = "Abuja"
    country: str = "Nigeria"
    currency: str = "NGN"
    timezone: str = "Africa/Lagos"

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "rideng_dev"
    db_user: str = "rideng_app"
    db_password: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()