"""Pydantic models for the control server API."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from agent.models import ActionType, CommandPayload, CommandStatus, ExecutionResult


class PushCommandRequest(BaseModel):
    """Request body for operators pushing a command to an agent queue."""

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


class QueuedCommand(BaseModel):
    """Internal representation of a command waiting in the agent queue."""

    command_id: UUID = Field(default_factory=uuid4)
    agent_id: str
    action: ActionType
    service: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    status: CommandStatus = CommandStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    result: ExecutionResult | None = None


class PushCommandResponse(BaseModel):
    command_id: UUID
    agent_id: str
    status: CommandStatus
    message: str = "command queued"


class PollResponse(BaseModel):
    """Agent poll response — command field matches agent-side CommandPayload."""

    command: CommandPayload | None = None


class HistoryEntry(BaseModel):
    command_id: UUID
    agent_id: str
    action: ActionType
    service: str | None
    status: CommandStatus
    created_at: datetime
    finished_at: datetime | None = None
    returncode: int | None = None
    error_message: str | None = None


class HistoryResponse(BaseModel):
    total: int
    entries: list[HistoryEntry]
