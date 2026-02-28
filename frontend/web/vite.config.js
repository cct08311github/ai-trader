import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// NOTE: CI/build should not depend on local absolute paths.
// Only enable local HTTPS dev certs when explicitly configured.

export default defineConfig(({ mode }) => {
  const enableLocalHttps = process.env.VITE_DEV_HTTPS === '1'

  return {
    plugins: [react()],
    server: {
      port: 3000,
      strictPort: true,
      host: '0.0.0.0',
      ...(enableLocalHttps
        ? {
            https: {
              key: process.env.VITE_HTTPS_KEY_PATH,
              cert: process.env.VITE_HTTPS_CERT_PATH
            }
          }
        : {})
    },
    test: {
      environment: 'jsdom',
      globals: true
    }
  }
})
