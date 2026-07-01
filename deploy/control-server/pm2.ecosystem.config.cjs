/**
 * PM2 — Control server (devdiaries.work / docker.devdiaries.work)
 *
 *   cd /home/projects/domain/docker-anywhere
 *   pm2 start deploy/control-server/pm2.ecosystem.config.cjs
 *   pm2 save && pm2 startup
 */
module.exports = {
  apps: [
    {
      name: "docker-anywhere-control",
      script: "./scripts/pm2-start-control.sh",
      interpreter: "bash",
      cwd: __dirname + "/../..",
      instances: 1,
      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 5000,
      time: true,
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      out_file: "./logs/control-out.log",
      error_file: "./logs/control-error.log",
    },
  ],
};
