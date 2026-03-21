const path = require('path');
const REPO = __dirname;
const HOME = process.env.HOME || process.env.USERPROFILE || '/tmp';

module.exports = {
  apps: [
    {
      name: "ai-trader-api",
      script: path.join(REPO, "frontend/backend/run.sh"),
      cwd: path.join(REPO, "frontend/backend"),
      interpreter: "bash",
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "development",
        DB_PATH: path.join(REPO, "data/sqlite/trades.db")
      }
    },
    {
      name: "ai-trader-web",
      script: "npm",
      args: "run dev -- --host 127.0.0.1 --port 3000",
      cwd: path.join(REPO, "frontend/web"),
      instances: 1,
      autorestart: true,
      watch: false,
      env: {
        NODE_ENV: "development"
      }
    }
    ,
    {
      name: "ai-trader-watcher",
      script: path.join(REPO, "bin/run_watcher.sh"),
      cwd: REPO,
      interpreter: "bash",
      instances: 1,
      autorestart: true,
      watch: false,
      kill_timeout: 30000,
      env: {
        OPENCLAW_CURRENT_IP: "127.0.0.1",
        WATCHER_TELEGRAM_BOT_TOKEN: "8773751510:AAHFORPaipYCA_993wx8B5fGH_eOAq5jqP0",
        WATCHER_TELEGRAM_CHAT_ID: "1017252031"
      }
    },
    {
      name: "ai-trader-agents",
      script: path.join(REPO, "bin/run_agents.sh"),
      cwd: REPO,
      interpreter: "bash",
      instances: 1,
      autorestart: true,
      restart_delay: 10000,
      max_restarts: 5,
      watch: false,
    },
    {
      name: "ai-trader-ops-summary",
      script: path.join(REPO, "bin/run_ops_summary.sh"),
      cwd: REPO,
      interpreter: "bash",
      instances: 1,
      autorestart: false,
      watch: false,
      cron_restart: "*/15 * * * *",
      env: {
        DB_PATH: path.join(REPO, "data/sqlite/trades.db"),
        OPS_SUMMARY_OUTPUT_DIR: path.join(REPO, "data/ops/ops_summary")
      }
    },
    {
      name: "ai-trader-reconciliation",
      script: path.join(REPO, "bin/run_reconciliation.sh"),
      cwd: REPO,
      interpreter: "bash",
      instances: 1,
      autorestart: false,
      watch: false,
      cron_restart: "45 16 * * 1-5",
      env: {
        DB_PATH: path.join(REPO, "data/sqlite/trades.db"),
        RECON_OUTPUT_DIR: path.join(REPO, "data/ops/reconciliation"),
        RECON_BROKER_SOURCE: "shioaji"
      }
    },
    {
      name: "ai-trader-incident-hygiene",
      script: path.join(REPO, "bin/run_incident_hygiene.sh"),
      cwd: REPO,
      interpreter: "bash",
      instances: 1,
      autorestart: false,
      watch: false,
      cron_restart: "55 16 * * 1-5",
      env: {
        DB_PATH: path.join(REPO, "data/sqlite/trades.db"),
        INCIDENT_HYGIENE_OUTPUT_DIR: path.join(REPO, "data/ops/incident_hygiene")
      }
    },
    {
      name: "ai-trader-db-backup",
      script: path.join(REPO, "bin/run_backup.sh"),
      cwd: REPO,
      interpreter: "bash",
      instances: 1,
      autorestart: false,
      watch: false,
      cron_restart: "0 2 * * *",
      env: {
        DB_PATH: path.join(REPO, "data/sqlite/trades.db"),
        BACKUP_DIR: path.join(REPO, "data/backup"),
        BACKUP_RETAIN: "30"
      }
    }
  ]
};
