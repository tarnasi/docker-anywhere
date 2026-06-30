#!/usr/bin/env python3
"""
Minimal CLI for operators to push signed commands to the control server.

Usage:
    uv run python -m control_server.cli push \\
        --url http://localhost:8000 \\
        --agent-id prod-server-01 \\
        --action docker_restart \\
        --service web

Requires OPERATOR_API_KEY and OPERATOR_HMAC_SECRET in environment.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time

import httpx


def _sign(
    method: str,
    path: str,
    body: bytes,
    api_key: str,
    secret: str,
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join([timestamp, nonce, method.upper(), path, body_hash])
    signature = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-API-Key": api_key,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }


def push_command(
    base_url: str,
    agent_id: str,
    action: str,
    service: str | None,
    params: dict,
    api_key: str,
    hmac_secret: str,
) -> None:
    body = {
        "agent_id": agent_id,
        "action": action,
        "service": service,
        "params": params,
    }
    body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
    path = "/api/v1/commands"
    headers = _sign("POST", path, body_bytes, api_key, hmac_secret)

    url = f"{base_url.rstrip('/')}{path}"
    response = httpx.post(url, content=body_bytes, headers=headers, timeout=30)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Control server operator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    push = sub.add_parser("push", help="Push a command to an agent queue")
    push.add_argument(
        "--url",
        default=os.getenv("CONTROL_SERVER_URL", "http://localhost:8000"),
    )
    push.add_argument("--agent-id", required=True)
    push.add_argument("--action", required=True)
    push.add_argument("--service", default=None)
    push.add_argument("--params", default="{}", help="JSON object of extra params")

    args = parser.parse_args()

    api_key = os.environ.get("OPERATOR_API_KEY", "")
    hmac_secret = os.environ.get("OPERATOR_HMAC_SECRET", "")
    if not api_key or not hmac_secret:
        print("Set OPERATOR_API_KEY and OPERATOR_HMAC_SECRET", file=sys.stderr)
        sys.exit(1)

    if args.command == "push":
        params = json.loads(args.params)
        push_command(
            args.url,
            args.agent_id,
            args.action,
            args.service,
            params,
            api_key,
            hmac_secret,
        )


if __name__ == "__main__":
    main()
