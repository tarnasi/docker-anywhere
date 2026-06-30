"""
Background asyncio poller that fetches and executes commands from the control server.

The agent ONLY initiates outbound HTTPS connections — it never accepts remote
command requests. This module is the core polling loop started at app startup.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from agent.config import settings
from agent.executor import execute_command
from agent.models import CommandPayload, ExecutionResult, PollResponse
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

        # Health/metrics state
        self.last_poll_at: datetime | None = None
        self.last_successful_poll_at: datetime | None = None
        self.commands_executed: int = 0
        self.consecutive_errors: int = 0

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the background polling loop."""
        if self.is_running:
            return

        self._client = httpx.AsyncClient(
            base_url=settings.control_server_url,
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,  # Prevent redirect-based SSRF tricks
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
        """Gracefully stop the polling loop and close the HTTP client."""
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
        """Main loop: poll → execute → report → sleep."""
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
                audit_event(
                    "poll_error",
                    consecutive_errors=self.consecutive_errors,
                )

            # Exponential backoff on repeated failures (capped at 5 minutes)
            if self.consecutive_errors > 0:
                backoff = min(
                    settings.poll_interval_seconds * (2 ** self.consecutive_errors),
                    300,
                )
                await asyncio.sleep(backoff)
            else:
                await asyncio.sleep(settings.poll_interval_seconds)

    async def _poll_once(self) -> None:
        """Single poll cycle: fetch pending command, execute, post result."""
        assert self._client is not None

        self.last_poll_at = datetime.now(UTC)
        poll_url = f"/api/v1/poll?agent_id={settings.agent_id}"

        response = await signed_request(self._client, "GET", poll_url)
        response.raise_for_status()

        self.last_successful_poll_at = datetime.now(UTC)
        poll_data = PollResponse.model_validate(response.json())

        if poll_data.command is None:
            logger.debug("no pending commands")
            return

        command = poll_data.command
        audit_event(
            "command_dequeued",
            command_id=str(command.command_id),
            action=command.action.value,
        )

        result = await execute_command(command)
        self.commands_executed += 1

        await self._post_result(result)

    async def _post_result(self, result: ExecutionResult) -> None:
        """POST execution result back to the control server."""
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


# Module-level singleton consumed by main.py lifespan and /health.
poller = AgentPoller()
