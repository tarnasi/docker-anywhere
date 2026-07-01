"""
Secure Polling Agent — FastAPI application entry point.

Exposes only a local /health endpoint for monitoring. All command execution
is driven by the outbound background poller — no inbound command API.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request, status

from agent.config import settings
from agent.models import HealthResponse
from agent.poller import poller
from agent.security import health_rate_limiter, setup_logging

logger = logging.getLogger("agent.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan: configure logging, start poller on startup,
    gracefully stop poller on shutdown.
    """
    setup_logging()
    logger.info(
        "starting secure polling agent",
        extra={"agent_id": settings.agent_id},
    )
    await poller.start()
    yield
    await poller.stop()
    logger.info("agent shutdown complete")


app = FastAPI(
    title="Secure Polling Agent",
    description=(
        "Outbound-only remote command execution agent. "
        "Polls a control server for whitelisted Docker/server actions."
    ),
    version="1.0.0",
    lifespan=lifespan,
    # Disable public docs in production — uncomment if needed:
    # docs_url=None,
    # redoc_url=None,
)


@app.get("/health", response_model=HealthResponse, tags=["monitoring"])
async def health(request: Request) -> HealthResponse:
    """
    Local health check for systemd / load balancer sidecar monitoring.

    Binds to 127.0.0.1 by default — not exposed to the public internet.
    Rate-limited per client IP to prevent abuse.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not health_rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
        )

    return HealthResponse(
        status="ok" if poller.is_running else "degraded",
        agent_id=settings.agent_id,
        poller_running=poller.is_running,
        last_poll_at=poller.last_poll_at,
        last_successful_poll_at=poller.last_successful_poll_at,
        last_inventory_sync_at=poller.last_inventory_sync_at,
        commands_executed=poller.commands_executed,
    )


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Minimal root response — confirms the agent process is alive."""
    return {
        "service": "secure-polling-agent",
        "agent_id": settings.agent_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }
