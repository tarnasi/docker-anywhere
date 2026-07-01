"""
Security utilities: HMAC request signing, rate limiting, and audit logging.

Outbound requests from the agent are signed so the control server can verify
authenticity and detect replay attacks via timestamp + nonce checks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

import httpx

from agent.config import settings

# ── Audit logger (separate from application logger) ───────────────────────────
audit_logger = logging.getLogger("agent.audit")


def setup_logging() -> None:
    """
    Configure application and audit loggers.

  Writes to both stderr and a rotating-friendly log file path. In production,
  pair with logrotate on `settings.log_file`.
    """
    log_level = getattr(logging, settings.log_level, logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [stream_handler]

    try:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    except OSError as exc:
        logging.getLogger("agent").warning(
            "file logging disabled (%s): %s", settings.log_file, exc
        )

    root = logging.getLogger("agent")
    root.setLevel(log_level)
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)

    audit_logger.setLevel(logging.INFO)
    audit_logger.handlers.clear()
    for handler in handlers:
        audit_logger.addHandler(handler)
    audit_logger.propagate = False


def audit_event(event: str, **details: Any) -> None:
    """
    Write a structured audit log entry.

    All security-sensitive events (polls, executions, auth failures) should
    go through this function for a consistent, searchable audit trail.
    """
    payload = {
        "event": event,
        "agent_id": settings.agent_id,
        "timestamp": datetime.now(UTC).isoformat(),
        **details,
    }
    audit_logger.info(json.dumps(payload, default=str))


# ── HMAC signing ──────────────────────────────────────────────────────────────

SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
NONCE_HEADER = "X-Nonce"
API_KEY_HEADER = "X-API-Key"


def _body_hash(body: bytes) -> str:
    """SHA-256 hex digest of the raw request body."""
    return hashlib.sha256(body).hexdigest()


def build_signature(
    method: str,
    path: str,
    body: bytes,
    timestamp: str,
    nonce: str,
    secret: str | None = None,
) -> str:
    """
    Compute HMAC-SHA256 signature for an HTTP request.

    Canonical string format (newline-separated):
        {timestamp}\\n{nonce}\\n{METHOD}\\n{path}\\n{body_sha256}
    """
    secret = secret or settings.hmac_secret
    canonical = "\n".join(
        [
            timestamp,
            nonce,
            method.upper(),
            path,
            _body_hash(body),
        ]
    )
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def signed_headers(
    method: str,
    path: str,
    body: bytes,
    api_key: str | None = None,
) -> dict[str, str]:
    """Build authentication headers for an outbound signed request."""
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    signature = build_signature(method, path, body, timestamp, nonce)

    return {
        API_KEY_HEADER: api_key or settings.api_key,
        TIMESTAMP_HEADER: timestamp,
        NONCE_HEADER: nonce,
        SIGNATURE_HEADER: signature,
        "Content-Type": "application/json",
    }


async def signed_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    """
    Perform an authenticated HTTP request to the control server.

    Serializes `json_body` to bytes, signs the request, and dispatches it.
    """
    body_bytes = b""
    if json_body is not None:
        body_bytes = json.dumps(json_body, separators=(",", ":"), default=str).encode("utf-8")

    # Extract path + query for signature (must match server verification).
    # httpx.URL.query may be bytes; decode it before building the canonical path.
    parsed = httpx.URL(url)
    sign_path = parsed.path
    if parsed.query:
        query = (
            parsed.query.decode("ascii")
            if isinstance(parsed.query, bytes)
            else str(parsed.query)
        )
        sign_path = f"{sign_path}?{query}"

    headers = signed_headers(method, sign_path, body_bytes)

    audit_event(
        "outbound_request",
        method=method,
        url=url,
        body_size=len(body_bytes),
    )

    return await client.request(method, url, content=body_bytes or None, headers=headers)


# ── Rate limiter (sliding window per key) ─────────────────────────────────────

class RateLimiter:
    """
    In-memory sliding-window rate limiter.

    Suitable for single-process deployments. For multi-worker setups, use Redis.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str) -> bool:
        """Return True if `key` is within rate limits."""
        now = time.monotonic()
        window_start = now - self.window_seconds
        hits = self._hits[key]

        while hits and hits[0] < window_start:
            hits.popleft()

        if len(hits) >= self.max_requests:
            audit_event("rate_limit_exceeded", key=key)
            return False

        hits.append(now)
        return True


# Health endpoint rate limiter — instantiated once at module load.
health_rate_limiter = RateLimiter(
    max_requests=settings.health_rate_limit_requests,
    window_seconds=settings.health_rate_limit_window_seconds,
)
