import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// NOTE: CI/build should not depend on local absolute paths.
// Only enable local HTTPS dev certs when explicitly configured.
export default defineConfig(({ mode }) => {
  return {
    plugins: [react()],
    server: {
      port: 3000,
      strictPort: true,
      host: '0.0.0.0'
    },
    test: {
      environment: 'jsdom',
      globals: true
    }
  }
})
