/**
 * PM2 config for devdiaries.work (control server only).
 *
 * Usage:
 *   cd /home/projects/domain/docker-anywhere
 *   pm2 start ecosystem.config.cjs
 *   pm2 save
 *   pm2 startup   # optional: auto-start on reboot
 */
module.exports = {
  apps: [
    {
      name: "docker-anywhere-control",
      script: "./scripts/pm2-start-control.sh",
      interpreter: "bash",
      cwd: __dirname,
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
