"""Pydantic models for the control server API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from agent.models import ActionType, CommandPayload, CommandStatus, ExecutionResult


class PushCommandRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128)
    action: ActionType
    service: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("agent_id must be alphanumeric (hyphens/underscores allowed)")
        return v


class PushCommandResponse(BaseModel):
    command_id: UUID | str
    agent_id: str
    status: CommandStatus
    message: str = "command queued"


class PollResponse(BaseModel):
    command: CommandPayload | None = None


class HistoryEntry(BaseModel):
    command_id: UUID | str
    agent_id: str
    action: ActionType
    service: str | None
    status: CommandStatus
    created_at: datetime | str
    finished_at: datetime | str | None = None
    returncode: int | None = None
    error_message: str | None = None


class HistoryResponse(BaseModel):
    total: int
    entries: list[HistoryEntry]


class ContainerRecord(BaseModel):
    container_id: str
    name: str | None = None
    image: str | None = None
    status: str | None = None
    state: str | None = None
    ports: str | None = None
    project_path: str | None = None
    labels: dict[str, Any] = Field(default_factory=dict)


class ImageRecord(BaseModel):
    image_id: str
    repository: str | None = None
    tag: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None


class NetworkRecord(BaseModel):
    network_id: str
    name: str | None = None
    driver: str | None = None
    scope: str | None = None


class InventorySyncRequest(BaseModel):
    agent_id: str
    containers: list[ContainerRecord] = Field(default_factory=list)
    images: list[ImageRecord] = Field(default_factory=list)
    networks: list[NetworkRecord] = Field(default_factory=list)


class CreateTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    action: ActionType
    service: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    category: str = "docker"


class UpdateTemplateRequest(BaseModel):
    name: str | None = None
    action: ActionType | None = None
    service: str | None = None
    params: dict[str, Any] | None = None
    description: str | None = None
    category: str | None = None


class CreateOrderRequest(BaseModel):
    agent_id: str
    template_id: int | None = None
    action: ActionType | None = None
    service: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    # If true, cancel any stuck pending/running order then queue this one.
    replace_active: bool = False


class OrderProgressRequest(BaseModel):
    command_id: UUID | str
    agent_id: str
    message: str = Field(..., min_length=1, max_length=4000)


class FailOrderRequest(BaseModel):
    command_id: UUID | str
    agent_id: str
    error_message: str = Field(..., min_length=1, max_length=2000)
