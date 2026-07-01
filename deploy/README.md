# Deployment files

| Server | Files | How to run |
|--------|-------|------------|
| **Control** (devdiaries) | `control-server/` | PM2 + Cloudflare Tunnel |
| **Private** (production) | `private-server/` | Hardened systemd |

---

## Control server — `docker.devdiaries.work`

Already running with PM2. Optional tunnel config:

```bash
# See control-server/cloudflared.config.example.yml
pm2 start cloudflared --name cloudflared-docker -- tunnel --config /etc/cloudflared/config.yml run
pm2 save
```

PM2 app:

```bash
pm2 start deploy/control-server/pm2.ecosystem.config.cjs
```

---

## Private server — agent install

### 1. Clone on private server

```bash
git clone <repo> /opt/docker-anywhere
cd /opt/docker-anywhere
```

### 2. Run install script (as root)

```bash
sudo bash deploy/private-server/install.sh
```

If `uv` is installed only for your user (e.g. `~/.local/bin/uv`), the script
finds it automatically. Override with: `UV_BIN=/path/to/uv sudo bash ...`

### 3. Configure agent

```bash
sudo nano /opt/docker-anywhere/agent/.env
```

```env
AGENT_ID=prod-server-01
API_KEY=<same as AGENT_API_KEY on control server>
HMAC_SECRET=<same as AGENT_HMAC_SECRET>
CONTROL_SERVER_URL=https://docker.devdiaries.work
REBOOT_CONFIRMATION_TOKEN=<random-16-chars>
LOG_FILE=/var/log/secure-agent/agent.log
```

`DOCKER_COMPOSE_FILE` and `DOCKER_WORK_DIR` are **optional** — compose projects are auto-detected.

### 4. systemd ReadWritePaths (optional)

Compose paths are **auto-detected** — you only need the agent install dir and logs:

```bash
sudo nano /etc/systemd/system/secure-agent.service
```

```ini
ReadWritePaths=/home/app/.docker/anywhere /var/log/secure-agent
```

Add extra paths only if you use `run_script` or set `DOCKER_COMPOSE_FILE` manually in `.env`.

```bash
sudo systemctl daemon-reload
```

### 5. Start agent

```bash
sudo systemctl start secure-agent
sudo systemctl status secure-agent
journalctl -u secure-agent -f
```

### 6. Verify on control server UI

Open https://docker.devdiaries.work — agent should show **Online** within ~15 seconds.

---

## Security (private server)

The systemd unit applies:

- Dedicated `dockeragent` user (no login shell)
- `ProtectSystem=strict` + `ReadOnlyPaths=/`
- Writable only: project dir, logs, your compose paths
- `NoNewPrivileges`, empty `CapabilityBoundingSet`
- Binds to `127.0.0.1:8080` only (local health check)
- **No inbound command API** — outbound HTTPS poll only

Optional reboot: `deploy/private-server/sudoers-reboot.example`

---

## File index

```
deploy/
├── README.md
├── control-server/
│   ├── pm2.ecosystem.config.cjs
│   ├── cloudflared.config.example.yml
│   └── nginx.docker.devdiaries.work.conf   # optional
└── private-server/
    ├── secure-agent.service
    ├── sudoers-reboot.example
    └── install.sh
```
