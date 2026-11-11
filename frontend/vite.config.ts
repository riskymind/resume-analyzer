/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Dev only: forward /api to the local backend so the browser stays
  // same-origin, matching production (Vercel rewrite / nginx proxy).
  const apiTarget = env.API_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
      },
    },
    // Vitest: components are tested in jsdom against a fake backend at the fetch/XHR boundary.
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{js,jsx,ts,tsx}'],
      restoreMocks: true,
      // Several 5 s findBy* waits can run in one test (see src/test/setup.ts).
      testTimeout: 15000,
      css: false,
    },
  }
})
