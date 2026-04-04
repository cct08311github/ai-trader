import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'fs'

const pkg = JSON.parse(readFileSync('./package.json', 'utf-8'))

// API backend: always on 127.0.0.1:8080 (HTTPS with self-signed cert)
// Proxy /api/* and /ws/* through the same origin (3012) so:
//  - Backend never needs to be exposed externally
//  - Browser avoids a second Tailscale hop for every API call
//  - CORS is automatically a non-issue (same origin)
const BACKEND = 'https://127.0.0.1:8080'

const proxyConfig = {
  '/ai-trader/api': {
    target: BACKEND,
    changeOrigin: true,
    secure: false,
    rewrite: (path) => path.replace(/^\/ai-trader/, ''),
  },
  '/api': {
    target: BACKEND,
    changeOrigin: true,
    secure: false,          // accept self-signed cert on loopback
  },
  '/ai-trader/ws': {
    target: BACKEND.replace('https', 'wss'),
    changeOrigin: true,
    secure: false,
    ws: true,
    rewrite: (path) => path.replace(/^\/ai-trader/, ''),
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
    base: '/ai-trader/',
    define: {
      __APP_VERSION__: JSON.stringify(pkg.version),
    },
    plugins: [react()],
    server: {
      port: 3012,
      strictPort: true,
      host: '0.0.0.0',
      proxy: proxyConfig,
    },
    preview: {
      port: 3012,
      host: '0.0.0.0',
      strictPort: true,
      proxy: proxyConfig,
      allowedHosts: [
        'mac-mini.tailde842d.ts.net',
        '.tailde842d.ts.net',
        'localhost',
        '127.0.0.1',
        'host.docker.internal',
      ],
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            'vendor-react': ['react', 'react-dom'],
            'vendor-router': ['react-router', 'react-router-dom'],
            'vendor-recharts': ['recharts'],
          },
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
    },
  }
})
