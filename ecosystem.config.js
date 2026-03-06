module.exports = {
  apps: [
    {
      name: "ai-trader-api",
      script: "/Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/backend/run.sh",
      cwd: "/Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/backend",
      interpreter: "bash",
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "development",
        DB_PATH: "/Users/openclaw/.openclaw/shared/projects/ai-trader/data/sqlite/trades.db"
      }
    },
    {
      name: "ai-trader-web",
      script: "npm",
      args: "run dev -- --host 127.0.0.1 --port 3000",
      cwd: "/Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/web",
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
      script: "/Users/openclaw/.openclaw/shared/projects/ai-trader/bin/run_watcher.sh",
      cwd: "/Users/openclaw/.openclaw/shared/projects/ai-trader",
      interpreter: "bash",
      instances: 1,
      autorestart: true,
      watch: false,
      env: {
        OPENCLAW_CURRENT_IP: "127.0.0.1"
      }
    },
    {
      name: "ai-trader-agents",
      script: "/Users/openclaw/.openclaw/shared/projects/ai-trader/bin/run_agents.sh",
      cwd: "/Users/openclaw/.openclaw/shared/projects/ai-trader",
      interpreter: "bash",
      instances: 1,
      autorestart: true,
      restart_delay: 10000,
      max_restarts: 5,
      watch: false,
    },
    {
      name: "ai-trader-ops-summary",
      script: "/Users/openclaw/.openclaw/shared/projects/ai-trader/bin/run_ops_summary.sh",
      cwd: "/Users/openclaw/.openclaw/shared/projects/ai-trader",
      interpreter: "bash",
      instances: 1,
      autorestart: false,
      watch: false,
      cron_restart: "*/15 * * * *",
      env: {
        DB_PATH: "/Users/openclaw/.openclaw/shared/projects/ai-trader/data/sqlite/trades.db",
        OPS_SUMMARY_OUTPUT_DIR: "/Users/openclaw/.openclaw/shared/projects/ai-trader/data/ops/ops_summary"
      }
    },
    {
      name: "ai-trader-reconciliation",
      script: "/Users/openclaw/.openclaw/shared/projects/ai-trader/bin/run_reconciliation.sh",
      cwd: "/Users/openclaw/.openclaw/shared/projects/ai-trader",
      interpreter: "bash",
      instances: 1,
      autorestart: false,
      watch: false,
      cron_restart: "45 16 * * 1-5",
      env: {
        DB_PATH: "/Users/openclaw/.openclaw/shared/projects/ai-trader/data/sqlite/trades.db",
        RECON_OUTPUT_DIR: "/Users/openclaw/.openclaw/shared/projects/ai-trader/data/ops/reconciliation",
        RECON_BROKER_SOURCE: "shioaji"
      }
    },
    {
      name: "ai-trader-incident-hygiene",
      script: "/Users/openclaw/.openclaw/shared/projects/ai-trader/bin/run_incident_hygiene.sh",
      cwd: "/Users/openclaw/.openclaw/shared/projects/ai-trader",
      interpreter: "bash",
      instances: 1,
      autorestart: false,
      watch: false,
      cron_restart: "55 16 * * 1-5",
      env: {
        DB_PATH: "/Users/openclaw/.openclaw/shared/projects/ai-trader/data/sqlite/trades.db",
        INCIDENT_HYGIENE_OUTPUT_DIR: "/Users/openclaw/.openclaw/shared/projects/ai-trader/data/ops/incident_hygiene"
      }
    }
  ]
};
