"""
Pydantic models for command payloads exchanged with the control server.

These models enforce strict typing and validation at the API boundary,
preventing unexpected fields from reaching the executor.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ActionType(StrEnum):
    """Whitelisted actions the agent is permitted to execute."""

    DOCKER_RESTART = "docker_restart"
    DOCKER_REBUILD = "docker_rebuild"
    DOCKER_LOGS = "docker_logs"
    DOCKER_STATUS = "docker_status"
    DOCKER_STOP = "docker_stop"
    DOCKER_START = "docker_start"
    DOCKER_COMPOSE_UP = "docker_compose_up"
    DOCKER_COMPOSE_DOWN = "docker_compose_down"
    DOCKER_COMPOSE_RESTART = "docker_compose_restart"
    COMPOSE_PROJECT_UP = "compose_project_up"
    COMPOSE_PROJECT_DOWN_RMI = "compose_project_down_rmi"
    COMPOSE_PROJECT_UP_FORCE = "compose_project_up_force"
    COMPOSE_PROJECT_BUILD_NOCACHE = "compose_project_build_nocache"
    COMPOSE_PROJECT_RESTART = "compose_project_restart"
    CONTAINERS_STOP_ALL = "containers_stop_all"
    CONTAINERS_REMOVE_ALL = "containers_remove_all"
    IMAGE_PULL = "image_pull"
    IMAGE_REMOVE = "image_remove"
    NETWORK_CREATE = "network_create"
    NETWORK_REMOVE = "network_remove"
    INVENTORY_SYNC = "inventory_sync"
    SERVER_REBOOT = "server_reboot"
    RUN_SCRIPT = "run_script"
    # One-shot: hard compose teardown + delete /home/app/witsml-server
    PURGE_WITSML_SERVER = "purge_witsml_server"


class CommandStatus(StrEnum):
    """Lifecycle status reported back to the control server."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"


class CommandPayload(BaseModel):
    """
    Command received from the control server during a poll.

    `service` is required for Docker actions; `params` carries action-specific
    data (e.g. confirmation token for reboot, script name for run_script).
    """

    command_id: UUID
    action: ActionType
    service: str | None = Field(
        default=None,
        description="Docker Compose service name (alphanumeric + hyphens only).",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific parameters.",
    )
    created_at: datetime | None = None

    @field_validator("service")
    @classmethod
    def validate_service_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("service name must be alphanumeric (hyphens/underscores allowed)")
        return v


class PollResponse(BaseModel):
    """Response body from GET /api/v1/poll on the control server."""

    command: CommandPayload | None = None


class ExecutionResult(BaseModel):
    """Result payload sent back to the control server after command execution."""

    command_id: UUID
    agent_id: str
    action: ActionType
    status: CommandStatus
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime
    duration_ms: int


class HealthResponse(BaseModel):
    """Local /health endpoint response."""

    status: str = "ok"
    agent_id: str
    poller_running: bool
    last_poll_at: datetime | None = None
    last_successful_poll_at: datetime | None = None
    last_inventory_sync_at: datetime | None = None
    commands_executed: int = 0
