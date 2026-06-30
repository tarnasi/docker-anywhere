"""
Minimal Control Server for the Secure Polling Agent.

Provides endpoints for operators to push commands and for agents to poll,
execute, and report results. Uses in-memory storage — suitable for demos;
replace with PostgreSQL/Redis for production persistence.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status

from agent.models import CommandPayload, CommandStatus, ExecutionResult
from control_server.config import settings
from control_server.models import (
    HistoryEntry,
    HistoryResponse,
    PollResponse,
    PushCommandRequest,
    PushCommandResponse,
    QueuedCommand,
)
from control_server.security import verify_signed_request

logger = logging.getLogger("control_server")


# ── In-memory stores ────────────────────────────────────────────────────────

# Per-agent FIFO command queues
_queues: dict[str, deque[QueuedCommand]] = defaultdict(deque)

# Full history for auditing / UI
_history: list[QueuedCommand] = []


def _trim_history() -> None:
    while len(_history) > settings.max_history_entries:
        _history.pop(0)


# ── Auth dependencies ───────────────────────────────────────────────────────

async def verify_agent_request(request: Request) -> bytes:
    return await verify_signed_request(
        request,
        expected_api_key=settings.agent_api_key,
        hmac_secret=settings.agent_hmac_secret,
    )


async def verify_operator_request(request: Request) -> bytes:
    return await verify_signed_request(
        request,
        expected_api_key=settings.operator_api_key,
        hmac_secret=settings.operator_hmac_secret,
    )


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logger.info("control server starting")
    yield
    logger.info("control server stopped")


app = FastAPI(
    title="Secure Agent Control Server",
    description="Push commands to agents and view execution history.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["monitoring"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "control-server"}


@app.post(
    "/api/v1/commands",
    response_model=PushCommandResponse,
    tags=["operator"],
)
async def push_command(
    raw: bytes = Depends(verify_operator_request),
) -> PushCommandResponse:
    """
    Queue a command for a specific agent.

    Requires operator API key + HMAC signature. The agent will pick up the
    command on its next poll cycle.
    """
    try:
        body = PushCommandRequest.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid command payload: {exc}",
        ) from exc

    cmd = QueuedCommand(
        agent_id=body.agent_id,
        action=body.action,
        service=body.service,
        params=body.params,
    )
    _queues[body.agent_id].append(cmd)
    _history.append(cmd)
    _trim_history()

    logger.info(
        "command queued",
        extra={"command_id": str(cmd.command_id), "agent_id": body.agent_id},
    )
    return PushCommandResponse(
        command_id=cmd.command_id,
        agent_id=body.agent_id,
        status=cmd.status,
    )


@app.get(
    "/api/v1/poll",
    response_model=PollResponse,
    tags=["agent"],
)
async def poll_commands(
    request: Request,
    agent_id: str,
    _raw: bytes = Depends(verify_agent_request),
) -> PollResponse:
    """
    Agent polls for the next pending command.

    Returns at most one command per poll. Commands are dequeued (FIFO).
    """
    queue = _queues.get(agent_id)
    if not queue:
        return PollResponse(command=None)

    # Skip already-running commands (shouldn't happen, but defensive)
    while queue:
        cmd = queue[0]
        if cmd.status == CommandStatus.PENDING:
            cmd.status = CommandStatus.RUNNING
            queue.popleft()

            # Return as CommandPayload (subset the agent expects)
            payload = CommandPayload(
                command_id=cmd.command_id,
                action=cmd.action,
                service=cmd.service,
                params=cmd.params,
                created_at=cmd.created_at,
            )
            logger.info(
                "command dispatched",
                extra={"command_id": str(cmd.command_id), "agent_id": agent_id},
            )
            return PollResponse(command=payload)

        queue.popleft()

    return PollResponse(command=None)


@app.post("/api/v1/results", tags=["agent"])
async def post_result(
    raw: bytes = Depends(verify_agent_request),
) -> dict[str, str]:
    """
    Agent posts execution result after running a command.

    Updates the in-memory history entry with stdout/stderr/returncode.
    """
    try:
        result = ExecutionResult.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid result payload: {exc}",
        ) from exc

    updated = False
    for entry in reversed(_history):
        if entry.command_id == result.command_id:
            entry.status = result.status
            entry.result = result
            updated = True
            break

    if not updated:
        logger.warning("result for unknown command_id=%s", result.command_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="command not found in history",
        )

    logger.info(
        "result received",
        extra={
            "command_id": str(result.command_id),
            "status": result.status.value,
            "returncode": result.returncode,
        },
    )
    return {"status": "accepted"}


@app.get(
    "/api/v1/history",
    response_model=HistoryResponse,
    tags=["operator"],
)
async def get_history(
    request: Request,
    agent_id: str | None = None,
    limit: int = 50,
    _raw: bytes = Depends(verify_operator_request),
) -> HistoryResponse:
    """
    View command execution history.

    Optionally filter by agent_id. Requires operator authentication.
    """
    limit = min(max(limit, 1), 500)
    entries = _history

    if agent_id:
        entries = [e for e in entries if e.agent_id == agent_id]

    entries = entries[-limit:]
    entries.reverse()

    history_entries = [
        HistoryEntry(
            command_id=e.command_id,
            agent_id=e.agent_id,
            action=e.action,
            service=e.service,
            status=e.status,
            created_at=e.created_at,
            finished_at=e.result.finished_at if e.result else None,
            returncode=e.result.returncode if e.result else None,
            error_message=e.result.error_message if e.result else None,
        )
        for e in entries
    ]

    return HistoryResponse(total=len(history_entries), entries=history_entries)
