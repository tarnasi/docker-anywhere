#!/usr/bin/env bash
# Install Docker Anywhere agent on a private production server.
# Run as root: sudo bash deploy/private-server/install.sh
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/docker-anywhere}"
AGENT_USER="${AGENT_USER:-dockeragent}"
AGENT_GROUP="${AGENT_GROUP:-dockeragent}"
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

find_uv() {
  local candidates=()
  [[ -n "${UV_BIN:-}" ]] && candidates+=("${UV_BIN}")
  command -v uv &>/dev/null && candidates+=("$(command -v uv)")
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    candidates+=("/home/${SUDO_USER}/.local/bin/uv")
  fi
  candidates+=(
    "/root/.local/bin/uv"
    "/usr/local/bin/uv"
    "/usr/bin/uv"
  )
  local c
  for c in "${candidates[@]}"; do
    [[ -n "$c" && -x "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}

install_uv_system() {
  echo "==> Installing uv to /usr/local/bin"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
}

ensure_uv() {
  local uv_path
  if uv_path="$(find_uv)"; then
    echo "==> Found uv: ${uv_path}"
    if [[ "${uv_path}" != "/usr/local/bin/uv" && ! -x /usr/local/bin/uv ]]; then
      install -m 755 "${uv_path}" /usr/local/bin/uv
      echo "==> Linked uv to /usr/local/bin/uv"
    fi
    return 0
  fi
  install_uv_system
  command -v /usr/local/bin/uv &>/dev/null
}

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

echo "==> Creating system user: ${AGENT_USER}"
if ! id "${AGENT_USER}" &>/dev/null; then
  useradd --system --home-dir "${INSTALL_DIR}" --shell /usr/sbin/nologin "${AGENT_USER}"
fi
usermod -aG docker "${AGENT_USER}" 2>/dev/null || true

echo "==> Creating log directory"
mkdir -p /var/log/secure-agent
chown "${AGENT_USER}:${AGENT_GROUP}" /var/log/secure-agent
chmod 750 /var/log/secure-agent

echo "==> Syncing project to ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
rsync -a --delete \
  --exclude '.git' --exclude '__pycache__' --exclude 'control_server/data' \
  --exclude 'logs' --exclude '.env' \
  "${PROJECT_ROOT}/" "${INSTALL_DIR}/"

chown -R "${AGENT_USER}:${AGENT_GROUP}" "${INSTALL_DIR}"

echo "==> Installing Python dependencies"
if ! ensure_uv; then
  echo "Failed to locate or install uv" >&2
  exit 1
fi

sudo -u "${AGENT_USER}" bash -c "cd ${INSTALL_DIR} && /usr/local/bin/uv sync"

if [[ ! -f "${INSTALL_DIR}/agent/.env" ]]; then
  cp "${INSTALL_DIR}/agent/.env.example" "${INSTALL_DIR}/agent/.env"
  chmod 600 "${INSTALL_DIR}/agent/.env"
  chown "${AGENT_USER}:${AGENT_GROUP}" "${INSTALL_DIR}/agent/.env"
  echo ""
  echo "!! Edit ${INSTALL_DIR}/agent/.env before starting the service"
  echo "   Required: AGENT_ID, API_KEY, HMAC_SECRET, CONTROL_SERVER_URL"
fi

echo "==> Installing systemd unit"
cp "${INSTALL_DIR}/deploy/private-server/secure-agent.service" /etc/systemd/system/secure-agent.service

echo ""
echo "==> IMPORTANT: Edit /etc/systemd/system/secure-agent.service"
echo "   Add your Docker project paths to ReadWritePaths, e.g.:"
echo "   ReadWritePaths=/opt/docker-anywhere /var/log/secure-agent /opt/app"
echo ""

systemctl daemon-reload
systemctl enable secure-agent

echo ""
echo "Done. Next steps:"
echo "  1. nano ${INSTALL_DIR}/agent/.env"
echo "  2. nano /etc/systemd/system/secure-agent.service  (ReadWritePaths)"
echo "  3. systemctl start secure-agent"
echo "  4. systemctl status secure-agent"
echo "  5. journalctl -u secure-agent -f"
