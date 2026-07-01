# Docker Anywhere

Secure **outbound-only** Docker management: your private server polls `devdiaries.work` for commands — no inbound ports on production.

## Architecture

```
Browser UI ──► Control Server (devdiaries.work) ◄── poll ── Agent (private server)
                      │                                      │
                      └── SQLite (orders, inventory)         └── docker CLI
```

- **One execute order at a time** per agent (queued until finished)
- **Live inventory**: containers, images, networks synced every poll cycle
- **Mobile-first web UI** at `/`

## Quick start (local)

```bash
uv sync

# Control server
cp control_server/.env.example control_server/.env
# Edit: AGENT_*, OPERATOR_*, UI_SECRET keys (openssl rand -hex 32)
uv run uvicorn control_server.main:app --host 0.0.0.0 --port 8000

# Agent (on machine with Docker)
cp agent/.env.example agent/.env
# Edit: AGENT_ID, API_KEY, HMAC_SECRET, CONTROL_SERVER_URL
uv run uvicorn agent.main:app --host 127.0.0.1 --port 8080
```

Open http://localhost:8000 — login with your `UI_SECRET`.

## Deploy to devdiaries.work (control server)

### 1. Copy project to server

```bash
ssh user@devdiaries.work
git clone <your-repo> /opt/docker-anywhere
cd /opt/docker-anywhere
uv sync
```

### 2. Configure environment

```bash
cp control_server/.env.example control_server/.env
nano control_server/.env
```

Generate secrets:

```bash
openssl rand -hex 32   # use for API keys and HMAC secrets
openssl rand -hex 24   # use for UI_SECRET
```

Set in `control_server/.env`:

| Variable | Description |
|----------|-------------|
| `AGENT_API_KEY` / `AGENT_HMAC_SECRET` | Shared with private server agent |
| `OPERATOR_API_KEY` / `OPERATOR_HMAC_SECRET` | For CLI automation |
| `UI_SECRET` | Browser login token |
| `DATABASE_PATH` | Optional, default `./data/docker-anywhere.db` |

### 3. Run with systemd

Create `/etc/systemd/system/docker-anywhere-control.service`:

```ini
[Unit]
Description=Docker Anywhere Control Server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/docker-anywhere
EnvironmentFile=/opt/docker-anywhere/control_server/.env
ExecStart=/opt/docker-anywhere/.venv/bin/uvicorn control_server.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 4. Reverse proxy (HTTPS required)

Example nginx snippet:

```nginx
server {
    server_name devdiaries.work;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Enable SSL with certbot, then:

```bash
sudo systemctl enable --now docker-anywhere-control
```

## Deploy agent (private production server)

```bash
cp agent/.env.example agent/.env
nano agent/.env
```

| Variable | Value |
|----------|-------|
| `AGENT_ID` | e.g. `prod-server-01` |
| `API_KEY` | Same as `AGENT_API_KEY` on control server |
| `HMAC_SECRET` | Same as `AGENT_HMAC_SECRET` |
| `CONTROL_SERVER_URL` | `https://devdiaries.work` |
| `DOCKER_COMPOSE_FILE` | Path to your compose file |
| `DOCKER_WORK_DIR` | Project directory |

Install systemd service:

```bash
sudo cp agent/agent.service /etc/systemd/system/secure-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now secure-agent
```

Ensure the agent user can run `docker` without password.

## Usage

1. Open **https://devdiaries.work** → login with `UI_SECRET`
2. View **Containers / Images / Networks** (auto-refreshes every 15s)
3. **Commands** tab — create reusable command templates
4. **Dashboard** — pick a template and run (one order at a time)
5. **Orders** — track execution status

### CLI (optional)

```bash
export OPERATOR_API_KEY=...
export OPERATOR_HMAC_SECRET=...
uv run python -m control_server.cli push \
  --url https://devdiaries.work \
  --agent-id prod-server-01 \
  --action docker_compose_up
```

## Supported actions

| Action | Description |
|--------|-------------|
| `docker_compose_up` | `docker compose up -d` |
| `docker_compose_down` | `docker compose down` |
| `docker_restart/stop/start/...` | Per-service compose commands |
| `containers_stop_all` | Stop all running containers |
| `containers_remove_all` | Prune stopped containers |
| `image_pull` / `image_remove` | Manage images |
| `network_create` / `network_remove` | Manage networks |
| `inventory_sync` | Force inventory refresh |

## Security notes

- Agent never accepts remote commands — outbound HTTPS only
- All API calls signed with HMAC-SHA256
- Commands mapped to fixed argv — no shell injection
- Use HTTPS in production (required)
