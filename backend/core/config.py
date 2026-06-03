"""
IntelliStock — Production Configuration
All secrets MUST come from environment variables. Never hardcode credentials.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Any

from pydantic import AnyHttpUrl, Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ─────────────────────────────────────────────────────────────────
    APP_NAME: str = "IntelliStock"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ── API Security ────────────────────────────────────────────────────────
    SECRET_KEY: str = Field(..., min_length=32)  # REQUIRED — no default
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    API_KEY_HEADER: str = "X-API-Key"

    # ── CORS ────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[AnyHttpUrl] = []
    ALLOWED_HOSTS: list[str] = ["*"]

    # ── Rate Limiting ───────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

    # ── Database (Postgres) ─────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn = Field(...)
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    DB_POOL_TIMEOUT: int = 30

    # ── Redis ───────────────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = Field(...)
    CACHE_TTL_SECONDS: int = 300  # 5 min default cache
    PREDICTION_CACHE_TTL: int = 900  # 15 min for predictions

    # ── ML Model Config ─────────────────────────────────────────────────────
    MODEL_STORE: str = "s3"  # "s3" | "gcs" | "azure" | "local"
    MODEL_BUCKET: str = "intellistock-models"
    MODEL_VERSION: str = "v1"
    SEQUENCE_LENGTH: int = 60  # 60 trading days look-back
    PREDICTION_HORIZON: int = 5  # predict next 5 days
    RETRAIN_INTERVAL_HOURS: int = 24

    # ── Cloud Storage ───────────────────────────────────────────────────────
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_REGION: str = "ap-south-1"  # Mumbai region — India-first

    GCP_PROJECT_ID: str | None = None
    GCP_SERVICE_ACCOUNT_KEY: str | None = None

    AZURE_STORAGE_CONNECTION_STRING: str | None = None

    # ── Monitoring ──────────────────────────────────────────────────────────
    SENTRY_DSN: str | None = None
    PROMETHEUS_ENABLED: bool = True
    OTEL_EXPORTER_ENDPOINT: str | None = None

    # ── Market Data ─────────────────────────────────────────────────────────
    DEFAULT_EXCHANGE: str = "NSE"
    DEFAULT_CURRENCY: str = "INR"
    MARKET_DATA_LOOKBACK_YEARS: int = 5
    YFINANCE_TIMEOUT: int = 30

    # ── Celery ──────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str | None = None  # defaults to REDIS_URL if not set
    CELERY_RESULT_BACKEND: str | None = None

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_must_be_strong(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def validate_environment(cls, v: Any) -> str:
        return str(v).lower()

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == Environment.DEVELOPMENT

    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or str(self.REDIS_URL)

    @property
    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or str(self.REDIS_URL)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — only reads env once."""
    return Settings()


settings = get_settings()
