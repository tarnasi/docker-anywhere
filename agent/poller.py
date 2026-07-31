"""
Background asyncio poller that fetches and executes commands from the control server.

The agent ONLY initiates outbound HTTPS connections — it never accepts remote
command requests. This module is the core polling loop started at app startup.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError

from agent.config import settings
from agent.executor import execute_command
from agent.inventory import collect_inventory
from agent.models import ActionType, CommandPayload, ExecutionResult, PollResponse
from agent.security import audit_event, signed_request

logger = logging.getLogger("agent.poller")


class AgentPoller:
    """
    Long-running background task that polls the control server on an interval.

    Maintains shared state for the /health endpoint (last poll time, counters).
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._client: httpx.AsyncClient | None = None

        self.last_poll_at: datetime | None = None
        self.last_successful_poll_at: datetime | None = None
        self.last_inventory_sync_at: datetime | None = None
        self.commands_executed: int = 0
        self.consecutive_errors: int = 0

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return

        self._client = httpx.AsyncClient(
            base_url=settings.control_server_url,
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
        )
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="agent-poller")
        logger.info(
            "poller started",
            extra={
                "interval": settings.poll_interval_seconds,
                "control_server": settings.control_server_url,
            },
        )
        audit_event("poller_started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._client:
            await self._client.aclose()
            self._client = None

        audit_event("poller_stopped")
        logger.info("poller stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._poll_once()
                self.consecutive_errors = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                self.consecutive_errors += 1
                logger.exception(
                    "poll cycle failed",
                    extra={"consecutive_errors": self.consecutive_errors},
                )
                audit_event("poll_error", consecutive_errors=self.consecutive_errors)

            if self.consecutive_errors > 0:
                backoff = min(
                    settings.poll_interval_seconds * (2 ** self.consecutive_errors),
                    300,
                )
                await asyncio.sleep(backoff)
            else:
                await asyncio.sleep(settings.poll_interval_seconds)

    async def _poll_once(self) -> None:
        assert self._client is not None

        self.last_poll_at = datetime.now(UTC)
        poll_url = f"/api/v1/poll?agent_id={settings.agent_id}"

        response = await signed_request(self._client, "GET", poll_url)
        response.raise_for_status()

        self.last_successful_poll_at = datetime.now(UTC)
        raw: dict[str, Any] = response.json()

        try:
            poll_data = PollResponse.model_validate(raw)
        except ValidationError as exc:
            # Unknown/newer action on an older agent — clear the stuck order.
            await self._fail_unparseable_command(raw, str(exc))
            await self._sync_inventory()
            return

        if poll_data.command is None:
            logger.debug("no pending commands")
            await self._sync_inventory()
            return

        command = poll_data.command
        audit_event(
            "command_dequeued",
            command_id=str(command.command_id),
            action=command.action.value,
        )

        async def on_progress(message: str) -> None:
            await self._post_progress(command.command_id, message)

        result = await execute_command(command, on_progress=on_progress)
        self.commands_executed += 1

        if command.action == ActionType.INVENTORY_SYNC:
            await self._sync_inventory()

        await self._post_result(result)
        await self._sync_inventory()

    async def _fail_unparseable_command(self, raw: dict[str, Any], reason: str) -> None:
        command = raw.get("command") if isinstance(raw, dict) else None
        if not isinstance(command, dict):
            logger.error("poll validation failed with no command object: %s", reason)
            return
        command_id = command.get("command_id")
        if not command_id:
            logger.error("poll validation failed with no command_id: %s", reason)
            return

        msg = f"agent cannot execute order (update agent): {reason[:500]}"
        logger.error("failing unparseable order %s: %s", command_id, msg)
        await self._post_fail(str(command_id), msg)
        audit_event("command_unparseable", command_id=str(command_id), reason=msg)

    async def _sync_inventory(self) -> None:
        assert self._client is not None
        try:
            data = await collect_inventory()
            body = {
                "agent_id": settings.agent_id,
                **data,
            }
            response = await signed_request(
                self._client,
                "POST",
                "/api/v1/inventory",
                json_body=body,
            )
            response.raise_for_status()
            self.last_inventory_sync_at = datetime.now(UTC)
            audit_event(
                "inventory_synced",
                containers=len(data["containers"]),
                images=len(data["images"]),
                networks=len(data["networks"]),
            )
        except Exception:
            logger.exception("inventory sync failed")

    async def _post_result(self, result: ExecutionResult) -> None:
        assert self._client is not None

        body = result.model_dump(mode="json")
        response = await signed_request(
            self._client,
            "POST",
            "/api/v1/results",
            json_body=body,
        )
        response.raise_for_status()
        audit_event(
            "result_posted",
            command_id=str(body.get("command_id")),
            status=body.get("status"),
        )

    async def _post_progress(self, command_id: UUID, message: str) -> None:
        assert self._client is not None
        try:
            response = await signed_request(
                self._client,
                "POST",
                "/api/v1/progress",
                json_body={
                    "command_id": str(command_id),
                    "agent_id": settings.agent_id,
                    "message": message,
                },
            )
            response.raise_for_status()
        except Exception:
            logger.exception("failed to post progress")

    async def _post_fail(self, command_id: str, error_message: str) -> None:
        assert self._client is not None
        response = await signed_request(
            self._client,
            "POST",
            "/api/v1/orders/fail",
            json_body={
                "command_id": command_id,
                "agent_id": settings.agent_id,
                "error_message": error_message,
            },
        )
        response.raise_for_status()


poller = AgentPoller()
