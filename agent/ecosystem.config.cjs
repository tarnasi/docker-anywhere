/**
 * PM2 — Agent (FastAPI + outbound poller)
 *
 * From project root:
 *   uv sync
 *   cp agent/.env.example agent/.env && nano agent/.env
 *   pm2 start agent/ecosystem.config.cjs
 *   pm2 save
 */
const path = require("path");

const root = path.join(__dirname, "..");

module.exports = {
  apps: [
    {
      name: "docker-anywhere-agent",
      cwd: root,
      script: path.join(root, ".venv/bin/uvicorn"),
      args: "agent.main:app --host 127.0.0.1 --port 9080",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 5,
      min_uptime: 5000,
      watch: false,
      time: true,
      out_file: path.join(root, "logs/agent-out.log"),
      error_file: path.join(root, "logs/agent-error.log"),
    },
  ],
};
