# Docker Anywhere

Secure **outbound-only** Docker management: your private server polls the control server for commands — no inbound ports on production.

## Architecture

```
Browser UI ──► Control Server (public HTTPS) ◄── poll ── Agent (private server)
                      │                                      │
                      └── SQLite (orders, inventory)         └── docker CLI
```

- **Multi-agent**: one control server, many agents (each with a unique `AGENT_ID`)
- **One execute order at a time** per agent (queued until finished)
- **Live inventory**: containers, images, networks synced every poll cycle
- **Mobile-first web UI** at `/`

## Project structure

```
docker-anywhere/
├── pyproject.toml          # Shared Python deps (uv)
├── uv.lock
├── agent/                  # Outbound polling agent (runs on Docker hosts)
│   ├── main.py             # FastAPI + background poller
│   ├── .env.example
│   └── ecosystem.config.cjs
├── control_server/         # Central API + web UI (public server)
│   ├── main.py             # FastAPI app
│   ├── cli.py              # Operator CLI
│   ├── static/             # Web UI (HTML/CSS/JS)
│   └── .env.example
├── deploy/                 # PM2, nginx, systemd configs
├── docs/                   # Documentation (HTML + PDF generator)
└── scripts/                # PM2 helper scripts
```

## Prerequisites

| Requirement | Control server | Agent |
|-------------|----------------|-------|
| Python 3.12+ | Yes | Yes |
| [uv](https://docs.astral.sh/uv/) | Yes | Yes |
| Docker CLI | No | Yes |
| PM2 (production) | Recommended | Recommended |

Install uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## How to build each project

This repo is a **monorepo** — one virtualenv at the root serves both the control server and the agent.

### 1. Root — install dependencies

From the repository root:

```bash
cd docker-anywhere
uv sync
```

This creates `.venv/` and installs FastAPI, httpx, pydantic-settings, etc. (see `pyproject.toml`).

Verify:

```bash
uv run python -c "import fastapi; print('ok')"
```

---

### 2. Control server

The control server is the central API, SQLite database, and web UI. It runs on your **public** machine (e.g. `docker.devdiaries.work`).

**Configure**

```bash
cp control_server/.env.example control_server/.env
```

Generate secrets:

```bash
openssl rand -hex 32   # AGENT_API_KEY, AGENT_HMAC_SECRET, OPERATOR_* keys
openssl rand -hex 24   # UI_SECRET (browser login)
```

Edit `control_server/.env` — at minimum set `AGENT_API_KEY`, `AGENT_HMAC_SECRET`, `OPERATOR_API_KEY`, `OPERATOR_HMAC_SECRET`, and `UI_SECRET`.

**Run (development)**

```bash
uv run uvicorn control_server.main:app --host 0.0.0.0 --port 8000 --reload
```

**Run (production — PM2)**

```bash
mkdir -p logs
chmod +x scripts/pm2-start-control.sh
pm2 start deploy/control-server/pm2.ecosystem.config.cjs
pm2 save
```

**Verify**

```bash
curl http://127.0.0.1:8000/health
# Open http://localhost:8000 and log in with UI_SECRET
```

| Item | Value |
|------|-------|
| Entry point | `control_server.main:app` |
| Default port | `8000` |
| Database | `control_server/data/docker-anywhere.db` (auto-created) |
| Web UI | `GET /` |

---

### 3. Agent

The agent runs on each **private** server that has Docker. It polls the control server outbound — no inbound command port is required.

**Configure**

```bash
cp agent/.env.example agent/.env
```

Edit `agent/.env`:

| Variable | Description |
|----------|-------------|
| `AGENT_ID` | Unique per machine (e.g. `prod-server-01`, `prod-server-02`) |
| `API_KEY` | Must match control server `AGENT_API_KEY` |
| `HMAC_SECRET` | Must match control server `AGENT_HMAC_SECRET` |
| `CONTROL_SERVER_URL` | Public URL of the control server |
| `REBOOT_CONFIRMATION_TOKEN` | Required if you use `server_reboot` |

**Run (development)**

```bash
uv run uvicorn agent.main:app --host 127.0.0.1 --port 9080
```

**Run (production — PM2)**

```bash
mkdir -p logs
pm2 start agent/ecosystem.config.cjs
pm2 save
```

**Verify**

```bash
curl http://127.0.0.1:9080/health
# Agent should appear in the web UI agent dropdown after first poll (~15s)
```

| Item | Value |
|------|-------|
| Entry point | `agent.main:app` |
| Default health port | `9080` (`HEALTH_PORT` in `.env`) |
| Poll interval | `15s` default (`POLL_INTERVAL_SECONDS`) |

Deploy multiple agents by copying the same repo to different servers and giving each a **different `AGENT_ID`**. They can share the same API keys.

---

### 4. Operator CLI

Optional command-line tool to push signed orders (automation, scripts, CI).

**Configure** — same credentials as `control_server/.env`:

```bash
export OPERATOR_API_KEY=...
export OPERATOR_HMAC_SECRET=...
```

**Run**

```bash
uv run python -m control_server.cli push \
  --url https://docker.devdiaries.work \
  --agent-id prod-server-01 \
  --action docker_compose_up
```

**History**

```bash
uv run python -m control_server.cli history \
  --url https://docker.devdiaries.work \
  --agent-id prod-server-01
```

| Item | Value |
|------|-------|
| Module | `control_server.cli` |
| Auth | HMAC + `OPERATOR_API_KEY` |

---

### 5. Documentation (optional)

Persian PDF documentation can be regenerated from `docs/`:

```bash
uv add fpdf2 arabic-reshaper python-bidi   # if not already installed
uv run python docs/generate_pdf.py
# Output: docs/docker-anywhere-documentation-fa.pdf
```

Static HTML docs: `docs/documentation-fa.html`

---

## Quick start (local — both services)

```bash
uv sync

# Terminal 1 — control server
cp control_server/.env.example control_server/.env
# Edit secrets, then:
uv run uvicorn control_server.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — agent (machine with Docker)
cp agent/.env.example agent/.env
# Edit AGENT_ID, API_KEY, HMAC_SECRET, CONTROL_SERVER_URL=http://localhost:8000
uv run uvicorn agent.main:app --host 127.0.0.1 --port 9080
```

Open http://localhost:8000 — log in with your `UI_SECRET`, then pick an agent from the header dropdown.

## Deploy files

All deployment configs live in [`deploy/`](deploy/README.md):

| Server | Path |
|--------|------|
| Control (devdiaries / docker.devdiaries.work) | `deploy/control-server/` |
| Private (agent) | `deploy/private-server/` |

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

### 3. Run with PM2 (recommended for devdiaries.work)

Install PM2 if needed:

```bash
npm install -g pm2
```

From the project root:

```bash
cd /home/projects/domain/docker-anywhere   # your path
uv sync
chmod +x scripts/pm2-start-control.sh
mkdir -p logs

pm2 start deploy/control-server/pm2.ecosystem.config.cjs
pm2 status
pm2 logs docker-anywhere-control --lines 50
```

Useful PM2 commands:

```bash
pm2 restart docker-anywhere-control
pm2 stop docker-anywhere-control
pm2 delete docker-anywhere-control
pm2 save                    # remember process list
pm2 startup                 # print command to auto-start on reboot
```

After `pm2 startup`, run the command it prints (usually with `sudo`).

Verify locally:

```bash
curl http://127.0.0.1:8000/health
```

### 3b. Run with systemd (alternative)

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

Enable SSL with certbot, then (if using systemd):

```bash
sudo systemctl enable --now docker-anywhere-control
```

If using PM2, nginx is enough — PM2 keeps the app running.

## Deploy agent (private production server)

**Simple guide:** [deploy/private-server/README.md](deploy/private-server/README.md)

```bash
cd /home/app/.docker/anywhere
bash deploy/private-server/setup.sh
nano agent/.env
pm2 start agent/ecosystem.config.cjs && pm2 save
```

## Usage

1. Open the control server URL → log in with `UI_SECRET`
2. Select an **agent** from the header dropdown (online/offline shown per agent)
3. View **Containers / Images / Networks** for that agent (auto-refreshes every 15s)
4. **Commands** tab — create reusable command templates
5. **Dashboard** — compose actions and quick-run templates
6. **Orders** — track execution status per agent

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
| `docker_compose_up` | `docker compose up -d` (all detected projects) |
| `docker_compose_down` | `docker compose down` |
| `docker_compose_restart` | `docker compose restart` (all projects) |
| `compose_project_up` | `docker compose up -d` in a project directory |
| `compose_project_restart` | `docker compose restart` in a project directory |
| `compose_project_down_rmi` | `docker compose down --rmi local` |
| `compose_project_up_force` | `docker compose up -d --force-recreate` |
| `compose_project_build_nocache` | `docker compose build --no-cache` |
| `docker_restart` / `stop` / `start` / `logs` | Per-container commands |
| `containers_stop_all` | Stop all running containers |
| `containers_remove_all` | Prune stopped containers |
| `image_pull` / `image_remove` | Manage images |
| `network_create` / `network_remove` | Manage networks |
| `inventory_sync` | Force inventory refresh |
| `server_reboot` | Reboot host (requires confirmation token) |

## Security notes

- Agent never accepts remote commands — outbound HTTPS only
- All API calls signed with HMAC-SHA256
- Commands mapped to fixed argv — no shell injection
- Use HTTPS in production (required)
