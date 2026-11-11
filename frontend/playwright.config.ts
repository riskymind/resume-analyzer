// Browser tests for the full user journey against the real API with the FAKE AI provider.
//
//   cd frontend && E2E_PYTHON=../backend/venv/bin/python npm run test:e2e
//
// Playwright starts both servers itself on dedicated ports:
//   - the API via `python -m scripts.mock_ai_server` (fake AI provider: no Gemini key is read and no AI credits are
//     used; it refuses to start with APP_ENV=production), with a throwaway SQLite database in a new temp directory;
//   - the Vite dev server, proxying /api to that API.
// Existing servers are never reused, so a run can never reach a real AI-backed backend or real user data.
//
// E2E_BASE_URL=http://localhost:8090 runs the same journey against an already-running stack instead, e.g. the
// Docker Compose stack with the fake AI provider (compose.fake-ai.yaml: nginx -> API -> PostgreSQL). No servers are
// started then. Only point it at a throwaway fake-AI stack: the journey registers and deletes an account.
//
// The browser is the locally installed Google Chrome (`channel: 'chrome'`), so no browser download is needed;
// GitHub's Ubuntu runners have Chrome preinstalled. Set E2E_BROWSER_CHANNEL='' to use Playwright's own Chromium.
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const API_PORT = Number(process.env.E2E_API_PORT || 8765)
const WEB_PORT = Number(process.env.E2E_WEB_PORT || 5174)
const python = process.env.E2E_PYTHON || 'python'
const dataDir = mkdtempSync(path.join(tmpdir(), 'ra-e2e-'))
const channel = process.env.E2E_BROWSER_CHANNEL ?? 'chrome'
const externalBaseUrl = process.env.E2E_BASE_URL

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: externalBaseUrl || `http://127.0.0.1:${WEB_PORT}`,
    acceptDownloads: true,
    // DOM snapshots are off: the recorder injects a script into every frame, which the sandboxed resume preview
    // (correctly) blocks and Chrome reports as a console error. Screenshots and actions are still recorded.
    trace: { mode: 'retain-on-failure', snapshots: false, screenshots: true },
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
    ...(channel ? { channel } : {}),
    viewport: { width: 1360, height: 900 },
  },
  webServer: externalBaseUrl
    ? []
    : [
        {
          command: `${python} -m scripts.mock_ai_server --data-dir ${dataDir} --port ${API_PORT} --allow-origin http://127.0.0.1:${WEB_PORT}`,
          cwd: path.resolve(import.meta.dirname, '../backend'),
          url: `http://127.0.0.1:${API_PORT}/api/health`,
          reuseExistingServer: false,
          timeout: 60_000,
          env: { APP_ENV: 'development' },
        },
        {
          command: `npx vite --port ${WEB_PORT} --strictPort --host 127.0.0.1`,
          url: `http://127.0.0.1:${WEB_PORT}`,
          reuseExistingServer: false,
          timeout: 60_000,
          env: { API_PROXY_TARGET: `http://127.0.0.1:${API_PORT}` },
        },
      ],
})
