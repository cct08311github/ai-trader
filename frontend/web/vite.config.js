import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    strictPort: true,
    host: '0.0.0.0',
    https: {
      key: fs.readFileSync('/Users/openclaw/.openclaw/shared/projects/agent-monitor-web/cert/key.pem'),
      cert: fs.readFileSync('/Users/openclaw/.openclaw/shared/projects/agent-monitor-web/cert/cert.pem')
    }
  }
})
