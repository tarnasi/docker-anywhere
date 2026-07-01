#!/usr/bin/env bash
# PM2 entrypoint for the control server on devdiaries.work
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/uvicorn" ]]; then
  echo "Missing .venv — run: uv sync" >&2
  exit 1
fi

if [[ ! -f "$ROOT/control_server/.env" ]]; then
  echo "Missing control_server/.env — run: cp control_server/.env.example control_server/.env" >&2
  exit 1
fi

# Bind localhost only — nginx proxies public traffic
exec "$ROOT/.venv/bin/uvicorn" control_server.main:app --host 127.0.0.1 --port 8000
