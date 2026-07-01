#!/usr/bin/env bash
# Simple agent setup — run as your own user (default: saxon)
# Usage: bash deploy/private-server/setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> Project: $ROOT"

if ! command -v uv &>/dev/null; then
  echo "Install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

echo "==> Installing Python packages"
uv sync

if [[ ! -f agent/.env ]]; then
  cp agent/.env.example agent/.env
  echo ""
  echo "Created agent/.env — edit these 4 values:"
  echo "  AGENT_ID, API_KEY, HMAC_SECRET, CONTROL_SERVER_URL"
  echo ""
  echo "  nano agent/.env"
  echo ""
fi

mkdir -p logs

echo "==> Done. Start the agent:"
echo ""
echo "  pm2 start agent/ecosystem.config.cjs"
echo "  pm2 save"
echo ""
echo "Or without PM2:"
echo ""
echo "  uv run uvicorn agent.main:app --host 127.0.0.1 --port 8080"
echo ""
