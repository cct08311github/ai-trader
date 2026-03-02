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
    }
  ]
};
