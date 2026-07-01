"""
Application configuration loaded from environment variables and .env file.

Uses Pydantic Settings v2 for validation, type coercion, and secure defaults.
All secrets must be provided via environment — never hard-code credentials.
"""

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / "agent" / ".env"


class Settings(BaseSettings):
    """Agent runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    agent_id: str = Field(
        ...,
        description="Unique identifier for this agent instance (reported to control server).",
    )
    api_key: str = Field(
        ...,
        min_length=32,
        description="Shared API key for authenticating with the control server.",
    )
    hmac_secret: str = Field(
        ...,
        min_length=32,
        description="Shared secret used to sign outbound HTTP requests (HMAC-SHA256).",
    )

    # ── Control server ────────────────────────────────────────────────────────
    control_server_url: str = Field(
        ...,
        description="Base URL of the control server, e.g. https://control.example.com",
    )
    poll_interval_seconds: int = Field(
        default=15,
        ge=5,
        le=300,
        description="Seconds between poll requests to the control server.",
    )
    request_timeout_seconds: float = Field(
        default=30.0,
        ge=5.0,
        description="HTTP timeout for outbound requests to the control server.",
    )

    # ── Docker paths (optional — compose projects are auto-detected via docker) ─
    docker_compose_file: Path | None = Field(
        default=None,
        description="Optional fallback compose file when auto-detection finds nothing.",
    )
    docker_work_dir: Path | None = Field(
        default=None,
        description="Optional fallback working directory for compose commands.",
    )

    # ── Script execution ──────────────────────────────────────────────────────
    allowed_scripts_dir: Path = Field(
        default=Path("/opt/app/scripts"),
        description="Directory containing whitelisted scripts for run_script action.",
    )

    # ── Protected actions ─────────────────────────────────────────────────────
    reboot_confirmation_token: str = Field(
        ...,
        min_length=16,
        description="Token that must be present in server_reboot command params.",
    )

    # ── Execution limits ──────────────────────────────────────────────────────
    command_timeout_seconds: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Maximum seconds a subprocess may run before being killed.",
    )
    max_output_bytes: int = Field(
        default=1_048_576,
        ge=1024,
        description="Truncate stdout/stderr beyond this size (bytes).",
    )

    # ── Rate limiting (local health endpoint) ─────────────────────────────────
    health_rate_limit_requests: int = Field(
        default=60,
        ge=1,
        description="Max /health requests per window per client IP.",
    )
    health_rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        description="Sliding window size for /health rate limiting.",
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    log_file: Path = Field(
        default=_PROJECT_ROOT / "logs" / "agent.log",
        description="Path to the agent log file (default: project logs/agent.log).",
    )
    log_level: str = Field(
        default="INFO",
        description="Python logging level (DEBUG, INFO, WARNING, ERROR).",
    )

    # ── Local health server (monitoring only — no remote commands) ────────────
    health_host: str = Field(
        default="127.0.0.1",
        description="Bind address for /health. Keep 127.0.0.1 in production.",
    )
    health_port: int = Field(
        default=8080,
        ge=1,
        le=65535,
        description="Port for the local health/metrics HTTP server.",
    )

    @field_validator("control_server_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        """Normalize base URL to avoid double-slash path joins."""
        return v.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def uppercase_log_level(cls, v: str) -> str:
        return v.upper()


# Singleton settings instance — import this throughout the agent package.
settings = Settings()
