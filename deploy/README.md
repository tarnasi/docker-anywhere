# Deployment files

| Server | Guide |
|--------|--------|
| **Control** (devdiaries) | `deploy/control-server/` + PM2 |
| **Private** (agent) | **[deploy/private-server/README.md](private-server/README.md)** |

## Private server — 3 commands

```bash
cd /home/app/.docker/anywhere
bash deploy/private-server/setup.sh
nano agent/.env
pm2 start agent/ecosystem.config.cjs && pm2 save
```

Runs as your user (`saxon`). No `dockeragent`, no hardening headaches.
