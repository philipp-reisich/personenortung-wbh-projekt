# path: rtls/api/config.py
"""Application configuration loaded from environment variables.

The `Settings` class uses Pydantic to read variables from the environment and
exposes typed attributes used throughout the API, such as database URLs,
secrets and other tuning parameters.
"""

from functools import lru_cache
from pydantic import BaseSettings, Field, AnyUrl


class Settings(BaseSettings):
    """Configuration values for the API service.

    Environment variables prefixed with `RTLS_` can be used to override
    settings. See `.env.example` for documentation of available variables.
    """

    database_url: AnyUrl = Field(..., env="DATABASE_URL")

    mqtt_broker_url: str = Field("mqtt://localhost:1883", env="MQTT_BROKER_URL")

    secret_key: str = Field(..., env="SECRET_KEY")

    token_lifetime_hours: int = Field(8, env="TOKEN_LIFETIME_HOURS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Return a cached settings instance.

    Using a cache prevents re-reading environment variables on every import.
    """
    return Settings()
