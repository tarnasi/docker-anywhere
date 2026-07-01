"""
Control server API — SQLite-backed command queue, inventory, and web UI.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent.models import ActionType, CommandPayload, CommandStatus, ExecutionResult
from control_server.config import settings
from control_server.database import db
from control_server.models import (
    CreateOrderRequest,
    CreateTemplateRequest,
    HistoryEntry,
    HistoryResponse,
    InventorySyncRequest,
    PollResponse,
    PushCommandRequest,
    PushCommandResponse,
    UpdateTemplateRequest,
)
from control_server.security import verify_signed_request

logger = logging.getLogger("control_server")

STATIC_DIR = Path(__file__).resolve().parent / "static"


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


async def verify_ui_request(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = auth[7:]
    if token != settings.ui_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid UI token")


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logger.info("control server starting db=%s", settings.database_path)
    yield
    logger.info("control server stopped")


app = FastAPI(
    title="Docker Anywhere Control Server",
    description="Outbound Docker management for devdiaries.work",
    version="2.0.0",
    lifespan=lifespan,
)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def ui_home() -> FileResponse:
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="UI not found")
    return FileResponse(index)


@app.get("/health", tags=["monitoring"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "control-server"}


# ── Agent endpoints ───────────────────────────────────────────────────────────

@app.get("/api/v1/poll", response_model=PollResponse, tags=["agent"])
async def poll_commands(
    agent_id: str,
    _raw: bytes = Depends(verify_agent_request),
) -> PollResponse:
    db.touch_agent_poll(agent_id)
    order = db.poll_next_order(agent_id)
    if not order:
        return PollResponse(command=None)

    payload = CommandPayload(
        command_id=UUID(order["command_id"]),
        action=ActionType(order["action"]),
        service=order.get("service"),
        params=order.get("params", {}),
        created_at=order.get("created_at"),
    )
    logger.info("command dispatched command_id=%s agent=%s", order["command_id"], agent_id)
    return PollResponse(command=payload)


@app.post("/api/v1/results", tags=["agent"])
async def post_result(
    raw: bytes = Depends(verify_agent_request),
) -> dict[str, str]:
    try:
        result = ExecutionResult.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid result payload: {exc}",
        ) from exc

    if not db.save_result(result):
        raise HTTPException(status_code=404, detail="command not found")

    logger.info(
        "result received command_id=%s status=%s",
        result.command_id,
        result.status.value,
    )
    return {"status": "accepted"}


@app.post("/api/v1/inventory", tags=["agent"])
async def sync_inventory(
    raw: bytes = Depends(verify_agent_request),
) -> dict[str, str]:
    try:
        body = InventorySyncRequest.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid inventory payload: {exc}",
        ) from exc

    db.replace_inventory(
        body.agent_id,
        [c.model_dump() for c in body.containers],
        [i.model_dump() for i in body.images],
        [n.model_dump() for n in body.networks],
    )
    logger.info(
        "inventory synced agent=%s containers=%d images=%d networks=%d",
        body.agent_id,
        len(body.containers),
        len(body.images),
        len(body.networks),
    )
    return {"status": "accepted"}


# ── Operator endpoints (HMAC — CLI / automation) ─────────────────────────────

@app.post("/api/v1/commands", response_model=PushCommandResponse, tags=["operator"])
async def push_command(
    raw: bytes = Depends(verify_operator_request),
) -> PushCommandResponse:
    try:
        body = PushCommandRequest.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid command payload: {exc}") from exc

    try:
        order = db.create_order(
            agent_id=body.agent_id,
            action=body.action.value,
            service=body.service,
            params=body.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return PushCommandResponse(
        command_id=order["command_id"],
        agent_id=body.agent_id,
        status=CommandStatus(order["status"]),
    )


@app.get("/api/v1/history", response_model=HistoryResponse, tags=["operator"])
async def get_history(
    agent_id: str | None = None,
    limit: int = 50,
    _raw: bytes = Depends(verify_operator_request),
) -> HistoryResponse:
    orders = db.list_orders(agent_id=agent_id, limit=limit)
    entries = [
        HistoryEntry(
            command_id=o["command_id"],
            agent_id=o["agent_id"],
            action=ActionType(o["action"]),
            service=o.get("service"),
            status=CommandStatus(o["status"]),
            created_at=o["created_at"],
            finished_at=o.get("finished_at"),
            returncode=o.get("returncode"),
            error_message=o.get("error_message"),
        )
        for o in orders
    ]
    return HistoryResponse(total=len(entries), entries=entries)


# ── Web UI API (Bearer UI_SECRET) ─────────────────────────────────────────────

@app.get("/api/ui/status", tags=["ui"])
async def ui_status(_: None = Depends(verify_ui_request)) -> dict[str, Any]:
    return {
        "agents": db.list_agents(),
        "api_log": db.get_api_log(),
    }


@app.get("/api/ui/containers", tags=["ui"])
async def ui_containers(
    agent_id: str | None = None,
    _: None = Depends(verify_ui_request),
) -> list[dict[str, Any]]:
    return db.list_containers(agent_id)


@app.get("/api/ui/images", tags=["ui"])
async def ui_images(
    agent_id: str | None = None,
    _: None = Depends(verify_ui_request),
) -> list[dict[str, Any]]:
    return db.list_images(agent_id)


@app.get("/api/ui/networks", tags=["ui"])
async def ui_networks(
    agent_id: str | None = None,
    _: None = Depends(verify_ui_request),
) -> list[dict[str, Any]]:
    return db.list_networks(agent_id)


@app.get("/api/ui/commands", tags=["ui"])
async def ui_commands(_: None = Depends(verify_ui_request)) -> list[dict[str, Any]]:
    return db.list_templates()


@app.post("/api/ui/commands", tags=["ui"])
async def ui_create_command(
    body: CreateTemplateRequest,
    _: None = Depends(verify_ui_request),
) -> dict[str, Any]:
    return db.create_template(
        name=body.name,
        action=body.action.value,
        service=body.service,
        params=body.params,
        description=body.description,
        category=body.category,
    )


@app.put("/api/ui/commands/{template_id}", tags=["ui"])
async def ui_update_command(
    template_id: int,
    body: UpdateTemplateRequest,
    _: None = Depends(verify_ui_request),
) -> dict[str, Any]:
    updated = db.update_template(
        template_id,
        name=body.name,
        action=body.action.value if body.action else None,
        service=body.service,
        params=body.params,
        description=body.description,
        category=body.category,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="template not found")
    return updated


@app.delete("/api/ui/commands/{template_id}", tags=["ui"])
async def ui_delete_command(
    template_id: int,
    _: None = Depends(verify_ui_request),
) -> dict[str, str]:
    if not db.delete_template(template_id):
        raise HTTPException(status_code=404, detail="template not found")
    return {"status": "deleted"}


@app.get("/api/ui/orders", tags=["ui"])
async def ui_orders(
    agent_id: str | None = None,
    limit: int = 50,
    _: None = Depends(verify_ui_request),
) -> list[dict[str, Any]]:
    return db.list_orders(agent_id=agent_id, limit=limit)


@app.get("/api/ui/orders/active", tags=["ui"])
async def ui_active_order(
    agent_id: str,
    _: None = Depends(verify_ui_request),
) -> dict[str, Any] | None:
    return db.get_active_order(agent_id)


@app.post("/api/ui/orders", tags=["ui"])
async def ui_create_order(
    body: CreateOrderRequest,
    _: None = Depends(verify_ui_request),
) -> dict[str, Any]:
    try:
        if body.template_id is not None:
            return db.create_order_from_template(body.agent_id, body.template_id)
        if not body.action:
            raise HTTPException(status_code=422, detail="action or template_id required")
        return db.create_order(
            agent_id=body.agent_id,
            action=body.action.value,
            service=body.service,
            params=body.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
