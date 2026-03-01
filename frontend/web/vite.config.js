import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// API backend: always on 127.0.0.1:8080 (HTTPS with self-signed cert)
// Proxy /api/* and /ws/* through the same origin (3012) so:
//  - Backend never needs to be exposed externally
//  - Browser avoids a second Tailscale hop for every API call
//  - CORS is automatically a non-issue (same origin)
const BACKEND = 'https://127.0.0.1:8080'

const proxyConfig = {
  '/api': {
    target: BACKEND,
    changeOrigin: true,
    secure: false,          // accept self-signed cert on loopback
  },
  '/ws': {
    target: BACKEND.replace('https', 'wss'),
    changeOrigin: true,
    secure: false,
    ws: true,
  },
}

export default defineConfig(({ mode }) => {
  return {
    plugins: [react()],
    server: {
      port: 3012,
      strictPort: true,
      host: '127.0.0.1',
      proxy: proxyConfig,
    },
    preview: {
      port: 3012,
      host: '127.0.0.1',
      strictPort: true,
      proxy: proxyConfig,
      allowedHosts: [
        'mac-mini.tailde842d.ts.net',
        '.tailde842d.ts.net',
        'localhost',
        '127.0.0.1',
      ],
    },
    test: {
      environment: 'jsdom',
      globals: true,
    },
  }
})
