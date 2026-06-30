"""Control server configuration."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Credentials shared with agents
    agent_api_key: str = Field(..., min_length=32)
    agent_hmac_secret: str = Field(..., min_length=32)

    # Separate credentials for operators pushing commands
    operator_api_key: str = Field(..., min_length=32)
    operator_hmac_secret: str = Field(..., min_length=32)

    # Request validation
    max_timestamp_skew_seconds: int = Field(default=300, ge=30)
    max_history_entries: int = Field(default=1000, ge=100)

    # Rate limiting
    rate_limit_requests: int = Field(default=120, ge=10)
    rate_limit_window_seconds: int = Field(default=60, ge=1)

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def uppercase_log_level(cls, v: str) -> str:
        return v.upper()


settings = Settings()
