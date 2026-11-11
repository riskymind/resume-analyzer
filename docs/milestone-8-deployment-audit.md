# Milestone 8 — Deployment Audit

_Date: 2026-11-10 · HEAD `ac8d085` on `main` · audience: developers preparing the deployment._

Milestones 1–7 are in the working tree but **uncommitted** (`git status` shows the whole `backend/app/`,
`docs/`, `.github/` and TypeScript frontend as untracked, the pre-refactor files as deleted). Nothing in this
milestone stages, commits or pushes.

## 1. What existed before this milestone

| Item | State |
|---|---|
| `Dockerfile` (backend / frontend) | **None.** The package list was verified in a throwaway QA container in Milestone 6 ([export-qa.md §5](export-qa.md)). |
| `.dockerignore` | None |
| Compose file | None |
| `render.yaml` | None |
| `vercel.json` | None |
| GitHub Actions | `.github/workflows/frontend.yml` (Milestone 7): frontend typecheck, ESLint, Prettier, Vitest, build, `npm audit`; Playwright journey with the fake AI provider; OpenAPI → TS types drift check. Never run on GitHub (nothing pushed). No backend or Docker jobs. |
| Env examples | `backend/.env.example` (backend only, complete for the settings that exist). No root example for Compose. |
| Deployment docs | [deployment-architecture.md](deployment-architecture.md) (proposed topology), [auth.md §2](auth.md#2-deployment-configuration) (cookie/CORS per environment) |

## 2. Runtime facts the infrastructure must respect

| Concern | Finding (file) |
|---|---|
| ASGI app | `app.main:app` via `create_app()` (`backend/app/application.py`). `backend/main.py` is a compatibility shim. |
| Health | `GET /api/health` (legacy alias) and `/api/v1/health` (liveness, no dependencies); `GET /api/v1/health/ready` (DB `SELECT 1` + AI provider configured, 503 otherwise). |
| Migrations | Alembic, 6 revisions (`app/db/migrations`). `app/db/migrate.py` runs them programmatically. `AUTO_MIGRATE` defaults to **true except in production**; there was **no CLI command** to run them deliberately and no protection against concurrent runs. |
| Config | `pydantic-settings` (`app/core/config.py`). Production refuses to start without `GEMINI_API_KEY`, with SQLite, with `*` or non-HTTPS `CORS_ORIGINS`, or with `COOKIE_SECURE=false`. Errors surface as a pydantic traceback. `postgres://` URLs are normalised to `postgresql+psycopg://`. |
| Client IP | `request.client.host` (`app/api/deps.py`), i.e. whatever uvicorn's proxy-header handling resolves. Login/registration rate limits key on it. uvicorn 0.54 with `FORWARDED_ALLOW_IPS='*'` takes the **leftmost** `X-Forwarded-For` entry. |
| CSRF / cookies | Origin check against `CORS_ORIGINS` + session-bound `X-CSRF-Token`. `__Host-ra_session` (Secure) in production, `ra_session` otherwise. Requires a same-origin `/api` proxy. |
| Streaming | No streaming responses or SSE. Exports are complete `Response` bodies with `Cache-Control: no-store`; other API responses set no `Cache-Control`. |
| Long requests | AI calls: per-attempt 60 s, overall deadline 90 s (`AI_TOTAL_TIMEOUT_SECONDS`). Any proxy in front must allow > 90 s. |
| Uploads | 5 MB per file, 12 MB per request (`BodySizeLimitMiddleware`). Proxies must allow ≥ 12 MB bodies. |
| PDF export | WeasyPrint 70 → needs Pango, HarfBuzz (+subset) and the template fonts (Carlito, Caladea, Liberation, DejaVu). Without Pango, PDF returns 503 and DOCX still works. |
| Fake AI | `scripts/mock_ai_server.py` + `tests.conftest.FakeLLM`; refuses `APP_ENV=production`; hard-wired to SQLite on `127.0.0.1`. |
| Tests | 785 backend tests pass (baseline, SQLite). The suite already supports PostgreSQL via `TEST_DATABASE_URL`. |

## 3. Frontend facts

| Concern | Finding |
|---|---|
| Build | `npm run build` = `tsc` + `vite build` → `frontend/dist` (static SPA, `react-router` 7 with `BrowserRouter`). |
| API base | Relative `/api` (`src/api/client.ts`); `VITE_API_BASE_URL` is an optional override and is the only `VITE_*` variable. |
| Dev proxy | Vite proxies `/api` → `API_PROXY_TARGET` (default `http://localhost:8000`). `API_PROXY_TARGET` is read in `vite.config.ts` only, never bundled. |
| Production proxy | Documented as a Vercel rewrite to `${API_ORIGIN}`, but **`rewrites` destinations cannot read environment variables.** Vercel's legacy `routes` syntax can (`"env": [...]`), and its `request.headers` transform can inject a secret header from an environment variable. |
| Deep links | `/resumes/:id`, `/reviews/:id`, `/matches/:id`, `/jobs/:id`, `/rewrites/:id`, `/account`, … need an `index.html` fallback on any static host. |
| Browser test | `e2e/workflow.spec.ts` uses relative URLs only, so it can target any base URL. `playwright.config.ts` always starts its own servers. |

## 4. Gaps and decisions taken in this milestone

| # | Gap | Resolution |
|---|---|---|
| A1 | The brief asks to keep "the backend URL and access key" server-only, but **no backend access key exists**. Without one, the Render URL is publicly reachable and a direct caller can forge `X-Forwarded-For`, bypassing per-IP limits (per-email and per-user limits still hold). | Added `BACKEND_ACCESS_KEY`: every request except the liveness probe `/api/v1/health` must carry a matching `X-Backend-Access-Key` header, which Vercel injects server-side. **Approved** (2026-11-11) with the condition that production fails closed: `APP_ENV=production` refuses to start without it. Disabled locally, in Compose and in tests unless a test exercises it. |
| A2 | `vercel.json` cannot use an env var in `rewrites`. | Use `routes` with `env` (backend URL) and a header transform (access key). |
| A3 | No way to run migrations deliberately or safely in parallel. | `python -m app.cli migrate` (PostgreSQL advisory lock) and `check-config` commands; Render `preDeployCommand`; Compose one-shot `migrate` service. |
| A4 | Production validation forbids `http://` origins, so a local Compose stack on `http://localhost:8080` **cannot** run with `APP_ENV=production` without weakening that check. | Compose runs the production image with production-like settings (PostgreSQL, JSON logs, explicit migrations, no source mounts) but `APP_ENV=development` (so `/api/docs` is enabled and cookies are not `Secure` locally). `APP_ENV=production` start-up and refusal behaviour of the image is verified separately with `docker run`. The check was not weakened. |
| A5 | Fake AI provider cannot run in a container (tests excluded, SQLite/loopback only). | A separate `fake-ai` image target (includes tests) and an isolated Compose override with its own project name and volume; `mock_ai_server.py` gains `--host` and `--database-url`. Never in the production image. |
| A6 | API responses carry no `Cache-Control`; Vercel now caches external rewrites per upstream headers. | API responses default to `Cache-Control: no-store` (explicit values kept); the Vercel route also disables rewrite caching. |
| A7 | Planned Render cron "retention purge" (`app.jobs.purge`) **does not exist**; there is no `DATA_RETENTION_DAYS`. | Not added to `render.yaml`. Recorded as not implemented. |
