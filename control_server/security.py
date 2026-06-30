"""
Control server security: HMAC verification, API key checks, rate limiting.

Mirrors the signing scheme used by the agent so both sides agree on the
canonical request format.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from control_server.config import settings

logger = logging.getLogger("control_server.security")

SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
NONCE_HEADER = "X-Nonce"
API_KEY_HEADER = "X-API-Key"

# Replay protection: track seen nonces (in-memory; use Redis in production)
_seen_nonces: dict[str, float] = {}
_NONCE_TTL_SECONDS = settings.max_timestamp_skew_seconds * 2


class RateLimiter:
    """Sliding-window rate limiter keyed by client IP."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        window_start = now - self.window_seconds
        hits = self._hits[key]

        while hits and hits[0] < window_start:
            hits.popleft()

        if len(hits) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
            )
        hits.append(now)


rate_limiter = RateLimiter(
    max_requests=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window_seconds,
)


def _body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _build_signature(
    method: str,
    path: str,
    body: bytes,
    timestamp: str,
    nonce: str,
    secret: str,
) -> str:
    canonical = "\n".join(
        [timestamp, nonce, method.upper(), path, _body_hash(body)]
    )
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _verify_timestamp(timestamp: str) -> None:
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid timestamp",
        ) from exc

    now = int(time.time())
    if abs(now - ts) > settings.max_timestamp_skew_seconds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="timestamp expired or skewed",
        )


def _check_nonce(nonce: str) -> None:
    """Reject replayed requests with the same nonce."""
    now = time.monotonic()

    # Prune expired nonces periodically
    expired = [k for k, t in _seen_nonces.items() if now - t > _NONCE_TTL_SECONDS]
    for k in expired:
        del _seen_nonces[k]

    if nonce in _seen_nonces:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="nonce already used (replay detected)",
        )
    _seen_nonces[nonce] = now


async def verify_signed_request(
    request: Request,
    *,
    expected_api_key: str,
    hmac_secret: str,
) -> bytes:
    """
    Validate API key, timestamp, nonce, and HMAC signature on an incoming request.

    Returns the raw request body bytes for downstream parsing.
    """
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter.check(client_ip)

    api_key = request.headers.get(API_KEY_HEADER)
    timestamp = request.headers.get(TIMESTAMP_HEADER)
    nonce = request.headers.get(NONCE_HEADER)
    signature = request.headers.get(SIGNATURE_HEADER)

    if not all([api_key, timestamp, nonce, signature]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing authentication headers",
        )

    if not hmac.compare_digest(api_key, expected_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid API key",
        )

    _verify_timestamp(timestamp)  # type: ignore[arg-type]
    _check_nonce(nonce)  # type: ignore[arg-type]

    body = await request.body()
    sign_path = request.url.path
    if request.url.query:
        sign_path = f"{sign_path}?{request.url.query}"

    expected_sig = _build_signature(
        request.method,
        sign_path,
        body,
        timestamp,  # type: ignore[arg-type]
        nonce,  # type: ignore[arg-type]
        hmac_secret,
    )

    if not hmac.compare_digest(signature, expected_sig):  # type: ignore[arg-type]
        logger.warning("invalid signature from %s for %s", client_ip, sign_path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signature",
        )

    return body
