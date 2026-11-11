# Deployment Architecture

_Status: **implemented in Milestone 8, re-verified locally in Milestone 9.** Nothing has been deployed;
deployment requires explicit authorization. Step-by-step guides: [deploy-render.md](deploy-render.md),
[deploy-vercel.md](deploy-vercel.md), [deploy-docker.md](deploy-docker.md). Verification results:
[milestone-9-final-report.md](milestone-9-final-report.md) (supersedes
[milestone-8-completion-report.md](milestone-8-completion-report.md) where they differ). The images, Compose
stacks and a production-mode topology were exercised locally. **Vercel and Render themselves have not been
exercised.** Where this document and the guides differ, the guides describe what was built._

## 1. Workload characteristics that drive the design

| Characteristic | Implication |
|---|---|
| LLM calls take 5–60 s (rewrite is the longest) | Needs generous request timeouts; avoid platforms with short function limits for the API |
| PDF generation via WeasyPrint needs Pango/Cairo/fonts | Needs a container image with system libraries rather than a bare serverless runtime |
| Resume PII, per-user data | Needs auth, managed Postgres, no files on ephemeral disks |
| Frontend is a static SPA (Vite build) | Ideal for a CDN/static host |
| Low, bursty traffic | One small API instance is enough; scale horizontally later (stateless API) |

## 2. Recommended topology

```
                    ┌────────────────────────────── Vercel ──────────────────────────────┐
 Browser ──HTTPS──► │  Static SPA (frontend/dist)                                        │
                    │  vercel.json route: /api/(.*) ──► ${BACKEND_URL}/api/$1            │
                    │    + header x-backend-access-key: $BACKEND_ACCESS_KEY (server-side)│
                    └──────────────────────────────────────────────┬─────────────────────┘
                                                                   │ (same-origin to the browser:
                                                                   │  httpOnly auth cookie works,
                                                                   │  no CORS needed)
                    ┌──────────────────────────── Render ──────────▼─────────────────────┐
                    │  Web Service (Docker): FastAPI + uvicorn, binds $PORT              │
                    │    /api/v1/health  → health check                                   │
                    │  Render Postgres (DATABASE_URL, internal URL)                       │
                    └──────────────────────────────┬─────────────────────────────────────┘
                                                   │ server-side only
                                                   ▼
                                          Gemini API (GEMINI_API_KEY)
```

**Why not run FastAPI on Vercel Functions?** Vercel's Python runtime can host FastAPI, but in this
app (a) WeasyPrint's native dependencies are not available in the function runtime, (b) long LLM
calls hit function duration limits on lower plans, and (c) the SQLite-on-disk fallback is impossible
there. Splitting static frontend (Vercel) from containerised API (Render) puts each workload on a
platform suited to it, as the project brief asks.

**Alternative (single platform, not implemented):** the frontend could also be a Render Static Site with an
`/api` rewrite and a key-injecting proxy. `render.yaml` does **not** define one (decision M8-11), because a
Render static-site rewrite cannot add the `X-Backend-Access-Key` header that production requires.

## 3. Environments

| Concern | Local (no Docker) | Docker Compose | Render / Vercel production |
|---|---|---|---|
| Frontend | `vite` dev server, proxy `/api` → `:8000` | `web` (nginx serving `dist`, proxy `/api` → `api`) | Vercel static + rewrite |
| API | `uvicorn --reload` | `api` container (non-root, healthcheck) | Render Docker web service |
| DB | SQLite file in `backend/data/` | Postgres 16 container + named volume | Render Postgres (or Neon) |
| Original uploaded files | Not stored (decision D3): only extracted text and structure are kept, in the database | same | same |
| Secrets | `backend/.env` | `.env` (never baked into images) | Render env vars / Vercel env vars |
| Logs | pretty console | JSON to stdout | JSON to stdout → platform log stream |

The frontend calls the **relative** path `/api` everywhere, so no backend URL is compiled into the
bundle. `VITE_API_BASE_URL` exists only as an override for unusual setups.

## 4. Container images

_As built (Milestone 8, re-verified in Milestone 9). Details: [deploy-docker.md](deploy-docker.md)._

**API (`backend/Dockerfile`, multi-stage, base `python:3.12.16-slim-bookworm`):**
1. `builder`: installs the pinned `requirements.txt` (wheels only) into `/opt/venv`, with a BuildKit pip cache.
2. `runtime` (= the default `production` target): WeasyPrint system libraries (`libpango-1.0-0`,
   `libpangoft2-1.0-0`, `libharfbuzz0b`, `libharfbuzz-subset0`) and the template fonts (`fonts-liberation`,
   `fonts-crosextra-carlito`, `fonts-crosextra-caladea`, `fonts-dejavu-core`). `fonts-noto-cjk` is opt-in
   (`INSTALL_CJK_FONTS=true`, **+169 MB**, 542 → 712 MB). Without it, CJK text renders as empty boxes in PDFs.
   Code is root-owned and read-only for the unprivileged `app` user (uid 10001). `HEALTHCHECK` on
   `/api/v1/health`.
3. Entrypoint: `python -m app.cli check-config` (readable errors, no values), optional
   `python -m app.cli migrate` when `RUN_MIGRATIONS_ON_START=true`, then
   `exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips … --timeout-graceful-shutdown ${GRACEFUL_SHUTDOWN_SECONDS:-25}`.
   Because of `exec`, uvicorn is PID 1 and receives SIGTERM, so shutdown is graceful.
4. `fake-ai` target (**test only**): the production image plus the test suite, dev tools and the fake AI server.

Migrations are **not** run by web processes. They run deliberately and advisory-locked
(`python -m app.cli migrate`) from Render's `preDeployCommand` or the Compose `migrate` service.

**Web (`frontend/Dockerfile`, multi-stage):** `node:24.22.2-alpine` build →
`nginxinc/nginx-unprivileged:1.28.2-alpine` (uid 101) serving `dist`, SPA fallback, `/api` proxy to the `api`
service (overwrites `X-Forwarded-For`), security headers. Used locally and in CI; production serves the same
build from Vercel.

`.dockerignore` excludes `.env*`, `*.db`, `data/`, virtualenvs, `node_modules`, caches and `.git`.

## 5. Docker Compose

- `docker compose up --build` runs a production-like stack: `web` (:8080) → `api` → `db` (Postgres),
  with healthcheck-gated `depends_on`, a one-shot `migrate` service, a named volume `pgdata`, and an
  internal database network (only `web` publishes a port, on 127.0.0.1).
- _As built:_ development is an override file (`compose.dev.yaml`) rather than a profile, so the default
  command stays production-like; `compose.fake-ai.yaml` runs the stack with the fake AI provider for tests.
- No MinIO/S3 profile: original uploads are not stored (decision D3), so there is nothing to put in object
  storage yet.

## 6. Render (`render.yaml`)

| Service | Type | Key config |
|---|---|---|
| `resume-analyzer-api` | `web`, `runtime: docker` | `dockerfilePath: ./backend/Dockerfile`, `healthCheckPath: /api/v1/health`, env from `fromDatabase` + `sync: false` secrets |
| `resume-analyzer-db` | `databases` (Postgres) | `DATABASE_URL` wired via `fromDatabase.connectionString` |

_As built:_ no purge cron job (the application has no retention purge command) and no optional Render static
site (Vercel hosts the frontend). Render injects `PORT`, which the entrypoint honours. Sessions are
server-side, so there is no `JWT_SECRET`; `BACKEND_ACCESS_KEY` uses `generateValue: true`; `GEMINI_API_KEY`
and `CORS_ORIGINS` are `sync: false` (entered in the dashboard). Migrations: `preDeployCommand`.

## 7. Vercel

- Project root: `frontend/`. Framework preset: Vite. Build: `npm run build`. Output: `dist`.
- `frontend/vercel.json` (_as built_): `rewrites` cannot read environment variables, so it uses `routes`:
  `/api/(.*)` → `${BACKEND_URL}/api/$1` with `"env": ["BACKEND_URL"]` and a `request.headers` transform
  that sets `x-backend-access-key` from `$BACKEND_ACCESS_KEY`; then the filesystem, a 404 for missing
  `/assets/*`, and the SPA fallback to `/index.html`; security headers on every response.
- The browser holds no secrets: the backend URL and access key exist only in Vercel's router.

## 8. Cross-cutting production concerns

| Concern | Approach |
|---|---|
| Config validation | `pydantic-settings`; in production the app refuses to start (one readable line per problem, never the values) unless `GEMINI_API_KEY` is set, `DATABASE_URL` is PostgreSQL, `CORS_ORIGINS` lists only HTTPS origins, `COOKIE_SECURE` is not disabled, and `BACKEND_ACCESS_KEY` has at least 32 characters. Sessions are server-side, so there is no JWT secret |
| Timeouts | Gemini per-attempt timeout (`AI_TIMEOUT_SECONDS`, default 60) and one overall deadline across retries (`AI_TOTAL_TIMEOUT_SECONDS`, default 90), uvicorn keep-alive and graceful shutdown, frontend `AbortController` |
| Rate limiting | Login (per IP + per email), registration (per IP), AI (per user per minute + daily quota). Counters live in the shared database (atomic upserts), so limits hold across workers and instances without Redis. See [auth.md](auth.md) |
| Health | `/api/v1/health` (liveness, no dependencies) and `/api/v1/health/ready` (DB ping + config) |
| Logging | JSON, request id, no resume text or tokens in logs (redaction filter) |
| Proxy headers | `--proxy-headers` + `FORWARDED_ALLOW_IPS` so rate limits key on the real client IP |
| Cookies / CSRF | Server-side sessions; `__Host-` prefixed `Secure; HttpOnly; SameSite=Lax` cookie; Origin check + session-bound CSRF token. Same-origin via rewrites, so no third-party-cookie problems. Configuration per environment: [auth.md](auth.md#2-deployment-configuration) |
| CI | GitHub Actions: lint, type-check, test, build, Docker build. **No deploy job** |

## 9. Known constraints

- Render free-tier web services sleep when idle. The first request after idle is slow, and free
  Postgres instances expire. A paid tier is advised for real use.
- Rate limits are stored in the database (see §8), so they survive restarts and hold across instances.
- Per-IP limits trust `X-Forwarded-For`. That is sound because `BACKEND_ACCESS_KEY` is mandatory in
  production (requests can only arrive through Vercel, which overwrites the header).
- The Vercel → Render rewrite adds one proxy hop. That is negligible next to LLM latency.
