# Private server agent

FastAPI app (`agent.main:app`) with a background poller. Local health only on `127.0.0.1:8080`.

## Setup

```bash
cd /home/app/.docker/anywhere
uv sync
cp agent/.env.example agent/.env
nano agent/.env
mkdir -p logs
```

Required in `agent/.env`:

```env
AGENT_ID=prod-server-01
API_KEY=<same as control server AGENT_API_KEY>
HMAC_SECRET=<same as control server AGENT_HMAC_SECRET>
CONTROL_SERVER_URL=https://docker.devdiaries.work
REBOOT_CONFIRMATION_TOKEN=any-random-16-chars
```

## PM2

```bash
pm2 start agent/ecosystem.config.cjs
pm2 save
pm2 logs docker-anywhere-agent
```

## Manual (dev)

```bash
uv run uvicorn agent.main:app --host 127.0.0.1 --port 8080
```

## Check

```bash
curl http://127.0.0.1:8080/health
```
