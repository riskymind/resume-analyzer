# Milestone 8 — Completion Report: Deployment Infrastructure, Docker & CI

_Date: 2026-11-10 · baseline HEAD `ac8d085` (`main`) · audience: the project owner reviewing Milestone 8 before
Milestone 9. Nothing was deployed, staged, committed or pushed._

## 1. Summary

| Area | Delivered | Verified how |
|---|---|---|
| API image | `backend/Dockerfile` (multi-stage, non-root, WeasyPrint + template fonts, `fake-ai` test target, opt-in CJK fonts), `docker-entrypoint.sh`, `.dockerignore` | Built and run locally (Docker 29.8, linux/amd64) |
| Web image | `frontend/Dockerfile` (Vite build → unprivileged nginx), nginx config with API proxy + SPA fallback, `.dockerignore` | Built and run locally |
| Compose | `compose.yaml` (production-like), `compose.dev.yaml` (hot reload), `compose.fake-ai.yaml` (isolated, no credentials) | All three started from clean volumes; smoke test + Playwright |
| Render | `render.yaml` (Docker web service + PostgreSQL 16, pre-deploy migration, generated access key, auto-deploy off) | Render's JSON schema; **not applied to Render** |
| Vercel | `frontend/vercel.json` (`routes`: env-based backend URL, server-side access-key header, SPA fallback) | Vercel's JSON schema + route-order emulation test; **not deployed** |
| CI | `backend.yml` and `docker.yml` (new), `frontend.yml` (comment only) | `actionlint` + shellcheck clean; the Docker job's image checks run locally; **workflows not run on GitHub** |
| Backend changes | `BACKEND_ACCESS_KEY` (required in production, fail closed); `no-store` default; `app.cli migrate` / `check-config`; advisory-locked migrations; **httpx/httpx2 bug fix**; log cleanup | 24 new tests; full suite on SQLite and PostgreSQL |
| Docs | Audit, Docker/Render/Vercel guides, env examples, README, architecture/plan updates, this report | — |

## 2. Files

**Created**

| File | Purpose |
|---|---|
| `backend/Dockerfile`, `backend/docker-entrypoint.sh`, `backend/.dockerignore` | API image |
| `frontend/Dockerfile`, `frontend/.dockerignore`, `frontend/nginx/default.conf.template`, `frontend/nginx/security-headers.conf` | Web image |
| `compose.yaml`, `compose.dev.yaml`, `compose.fake-ai.yaml` | Local stacks |
| `render.yaml` | Render Blueprint |
| `frontend/vercel.json` | Vercel project configuration |
| `.env.example` (root) | Compose variables |
| `.github/workflows/backend.yml`, `.github/workflows/docker.yml` | CI |
| `scripts/smoke_test_stack.py` | Stdlib-only end-to-end check of a running stack |
| `backend/tests/integration/test_deployment.py` | Access key, cache header, CLI, locked migrations, logging, import-without-httpx |
| `frontend/src/deployment/vercelConfig.test.ts` | `vercel.json` static checks and route emulation |
| `docs/milestone-8-deployment-audit.md`, `docs/deploy-docker.md`, `docs/deploy-render.md`, `docs/deploy-vercel.md`, `docs/milestone-8-completion-report.md` | Documentation |

**Modified**

| File | Change |
|---|---|
| `backend/app/core/config.py` | `backend_access_key` setting (blank → unset; ≥ 32 chars in production) |
| `backend/app/core/middleware.py` | `BackendAccessKeyMiddleware`; default `Cache-Control: no-store` |
| `backend/app/application.py` | Installs the access-key middleware when configured; logs whether it is required |
| `backend/app/core/logging.py` | Drops uvicorn's ANSI `color_message` from JSON logs |
| `backend/app/cli.py` | `check-config` and `migrate` commands; configuration errors printed per variable, without values or traceback |
| `backend/app/db/migrate.py`, `backend/app/db/session.py` | `run_migrations_exclusively` (PostgreSQL advisory lock), revision helpers; dev auto-migrate uses the lock |
| `backend/app/ai/gemini.py` | Recognises `httpx2` **and** `httpx` transport/timeout errors; no hard dependency on `httpx` (bug fix, §11) |
| `backend/requirements.txt`, `backend/requirements-dev.txt` | `httpx2==2.16.0` moved to runtime (was dev-only); `httpx` marked tests-only |
| `backend/scripts/mock_ai_server.py` | `--host`, `--database-url`; always one worker |
| `backend/tests/unit/test_gemini_adapter.py` | `httpx2` and `httpx` retry/timeout regression tests |
| `backend/.env.example` | `BACKEND_ACCESS_KEY`, container-only variables, migration note |
| `frontend/playwright.config.ts` | `E2E_BASE_URL` runs the journey against an already-running stack (default unchanged) |
| `.github/workflows/frontend.yml` | Header comment only (points to the new workflows); jobs unchanged |
| `.gitignore` | Root `/.env`, `.env.local`, `frontend/.vercel/` |
| `README.md` | Docker quick start, deployment table, CI summary |
| `docs/deployment-architecture.md`, `docs/refactoring-plan.md` (§8 row, new §14), `docs/export-qa.md`, `docs/rewriting.md` | As-built notes and decisions |

**Removed:** none.

## 3. Docker image builds

| Image | Result | Size | Notes |
|---|---|---|---|
| `resume-analyzer-api` (production, default target) | ✅ builds | **542 MB** | Rebuild after a code change: ~21 s (layer + pip wheel cache) |
| `resume-analyzer-api` `INSTALL_CJK_FONTS=true` | ✅ builds | 712 MB | §12 |
| `resume-analyzer-api:fake-ai` | ✅ builds | 716 MB | Test only |
| `resume-analyzer-web` (runtime) | ✅ builds | **82 MB** | No Node, no `node_modules` |
| `resume-analyzer-web:dev` | ✅ builds | 528 MB | Development only |

Image checks (all passed): API runs as **uid 10001** and web as **uid 101**; the API user cannot write to the
code; the production image contains no project tests, no `.env`, no database files and no dev tools (pytest,
ruff, mypy absent); all five template font families resolve to their metric-compatible fonts (Carlito,
Caladea, Liberation Sans/Serif); WeasyPrint 70.0 imports with Pango; no Fontconfig warnings (fixed during
verification: the unprivileged user had no writable cache directory).

## 4. Compose start-up and health checks

| Stack | From clean volumes | Result |
|---|---|---|
| Production-like (`compose.yaml`) | ✅ | `db` healthy → `migrate` exited 0 → `api` healthy (2 workers) → `web` healthy; `/healthz` ok; `/api/v1/health` ok; `/api/v1/health/ready` = `degraded` (`database: ok`, `ai_provider: not_configured`, as expected without a key) |
| Development (`+ compose.dev.yaml`) | ✅ | Started in 68 s; API on 127.0.0.1:8000 (`/api/docs` 200), Vite on 127.0.0.1:5173 proxying `/api`, PostgreSQL on 127.0.0.1:5433; **uvicorn and Vite both hot-reloaded** after a file change. A bug was found and fixed: the database port was not published, because Docker cannot publish ports for a container attached only to an internal network. |
| Fake AI (`+ compose.fake-ai.yaml`, own project) | ✅ | All healthy; smoke test and Playwright below |

Further checks on the production-like stack:

- **Persistence:** an account created before `docker compose down` was still there after `up`; the volume was kept, and the re-run `migrate` reported "Already up to date at revision 0006".
- **Graceful shutdown:** `docker compose stop api` → SIGTERM → both workers ran the lifespan shutdown → exit 0 in 0.7 s. Not tested: an in-flight request during shutdown (uvicorn's documented behaviour is relied on).
- **Production mode** (`APP_ENV=production`, the image against the Compose PostgreSQL, placeholder Gemini key, no AI endpoint called):
  - Started healthy.
  - Missing configuration → `Configuration error:` with one line per variable, exit 1, no traceback.
  - `/api/docs` and `/api/openapi.json` → 404.
  - Cookie `__Host-ra_session` with `Secure; HttpOnly; SameSite; Path; Max-Age`.
  - Login with an untrusted `Origin` → 403.
  - Access key: liveness 200 without the key; readiness 403 without it, 200 with it.
  - Without `BACKEND_ACCESS_KEY` the production image exits 1 with `BACKEND_ACCESS_KEY must be set in production` (re-verified after the approval follow-up, §16).
  - `Cache-Control: no-store`.
  - **This check found the httpx bug (§11)**: before the fix, the production image crashed at start-up whenever a Gemini key was set.

## 5. PostgreSQL and migrations

| Check | Result |
|---|---|
| Fresh database → head (`python -m app.cli migrate`, Compose `migrate` service) | ✅ `(empty database) -> 0006`, 15 tables |
| Idempotent re-run | ✅ "Already up to date" |
| Four concurrent `migrate` runs on an empty PostgreSQL schema (advisory lock) | ✅ (test `test_concurrent_migrations_are_serialised_on_postgres`) |
| `alembic check` (models vs migrations) on PostgreSQL 16.15 | ✅ "No new upgrade operations detected" |
| `alembic downgrade base` → `upgrade head` on PostgreSQL | ✅ |
| Production `DATABASE_URL` in Render form (`postgres://…`) | ✅ normalised to psycopg 3 |

## 6. Backend and frontend tests (final run, final code)

| Suite | Result |
|---|---|
| `ruff check`, `ruff format --check`, `mypy app scripts` (strict), root `scripts/` lint + strict mypy | ✅ clean |
| Backend tests, SQLite | ✅ **808 passed**, 1 skipped (the PostgreSQL-only lock test) — baseline was 785 |
| Backend tests, PostgreSQL 16.15 (`TEST_DATABASE_URL`) | ✅ **809 passed**, 0 skipped |
| `pip-audit -r requirements.txt --strict` | ✅ no known vulnerabilities |
| Frontend `npm run check` (typecheck, ESLint, Prettier, Vitest, build) | ✅ **97/97 tests** (77 before + 20 new) |
| `npm audit` | ✅ 0 vulnerabilities |
| Stack smoke test, fake-AI stack (`scripts/smoke_test_stack.py`) | ✅ **38/38**: deep links, JSON 404 for unknown API routes, asset 404, security headers, `no-store`, register/session/CSRF refusals, resume upload, job parsing, deterministic match, rewrite, **5 templates × PDF and DOCX**, cross-account 404, account deletion |
| Stack smoke test, production-like stack (`--no-ai`) | ✅ 20/20 |

**Pre-existing flake (not fixed):** in the baseline run, while a Docker pull was saturating the machine,
`Rewrite.test.jsx › requires a resume, then sends …` timed out at 5.56 s against Vitest's 5 s default. It
passed on every later run (23/23 alone, 97/97 in full). It could flake on slow CI runners; raising that
test's timeout is a one-line change, not made without approval.

## 7. Playwright

| Run | Result |
|---|---|
| Default mode (own Vite + fake-AI server, SQLite, as in `frontend.yml`) | ✅ 16/16 |
| **Against the containerised fake-AI stack** (`E2E_BASE_URL=http://localhost:8090`: nginx → API → PostgreSQL) | ✅ 16/16, run twice (before and after the final image rebuild). Covers sign-in, upload, match, rewrite, accept/reject, unverified-claim acknowledgement, PDF and DOCX downloads, all template previews, versions, **deep links surviving a reload**, 390/768 px layouts, account deletion, and "no JS errors, no 5xx" |

## 8. Render configuration

`render.yaml`: web service `resume-analyzer-api` (`runtime: docker`, context `./backend`, plan `starter`,
region `oregon`), health check `/api/v1/health`, `preDeployCommand: python -m app.cli migrate`,
`autoDeployTrigger: "off"`, `maxShutdownDelaySeconds: 120`, `buildFilter` on `backend/**`; PostgreSQL 16
`resume-analyzer-db` (`basic-256mb`, `ipAllowList: []`). Environment: `APP_ENV=production`, `DATABASE_URL`
from the database, `GEMINI_API_KEY` and `CORS_ORIGINS` as `sync: false`, `BACKEND_ACCESS_KEY` generated,
`FORWARDED_ALLOW_IPS=*`, `WEB_CONCURRENCY=1`, `GRACEFUL_SHUTDOWN_SECONDS=100`. Validated against
`https://render.com/schema/render.yaml.json`. The Render CLI's `render blueprints validate` was **not run**
(the CLI is not installed and needs an account). Guide: [deploy-render.md](deploy-render.md).

## 9. Vercel configuration

`frontend/vercel.json`: framework Vite, `npm ci` / `npm run build` / `dist`. `routes`:

1. Security headers on every response.
2. `/api/(.*)` → `${BACKEND_URL}/api/$1`, with `x-backend-access-key` set from `$BACKEND_ACCESS_KEY`. This route ends routing.
3. Immutable cache headers for `/assets/*`.
4. Filesystem.
5. 404 for a missing asset.
6. SPA fallback to `/index.html`.

Both variables are server-side; there are no `VITE_*` variables. The file is validated against
`https://openapi.vercel.sh/vercel.json`, and the route emulation test covers every deep-link route, the API
paths (including `/api/index.html`), assets and headers. Guide: [deploy-vercel.md](deploy-vercel.md).

## 10. GitHub Actions

| Workflow | Jobs |
|---|---|
| `frontend.yml` (Milestone 7, unchanged jobs) | Frontend checks + `npm audit`; Playwright with the fake-AI server; OpenAPI type drift |
| `backend.yml` (new) | Lint (ruff, format, strict mypy, root scripts, `pip-audit`); tests on SQLite; tests on a PostgreSQL 16 service + migrations from empty, idempotency, `alembic check`, downgrade/upgrade round trip |
| `docker.yml` (new) | Compose config validation (incl. missing-password failure); Render/Vercel schema validation; manifest secret check; production image builds; image checks (users, no test code, start-up refusal, **production-mode start against PostgreSQL with the access key**); bundle secret scan; fake-AI Compose stack; smoke test; Playwright against the containers; log scan for errors and leaked data; teardown |

No workflow deploys, publishes or pushes images. None needs secrets: the CI database passwords are
throwaway values or generated per run, and AI is always the fake provider. **The workflows have not run on
GitHub** (nothing was pushed). They pass `actionlint` 1.7.8 with shellcheck. The `docker.yml` image-check
step was extracted and run locally, and passed. While reviewing my own workflow I fixed two defects before
they could run: `! cmd` lines that `bash -e` never treats as failures, and a Buildx setup step that would have
kept built images out of `docker run`.

## 11. Security review and secret-exposure checks

| Check | Result |
|---|---|
| Frontend bundle built with canary values in `BACKEND_ACCESS_KEY`, `BACKEND_URL`, `GEMINI_API_KEY`, `API_PROXY_TARGET`, `DATABASE_URL` | ✅ 0 occurrences of the canary or any variable name; no `localhost:8000`, `onrender`, `VITE_` |
| Web runtime image | ✅ no secrets, no Node |
| API image | ✅ no `.env`, no `*.db`, no tests; secrets only at run time |
| Container logs (both stacks, after the smoke test and Playwright) | ✅ 0 errors/tracebacks; 0 occurrences of the DB password, CSRF tokens, session cookies, test passwords or resume text |
| Configuration errors and the `check-config` summary | ✅ never print values; the DB password is masked |
| Access-key middleware | ✅ constant-time comparison; refusals logged without the key (tested) |
| Manifests | ✅ no secrets in `render.yaml`, `vercel.json`, Compose files; only the ephemeral CI DB password in `docker.yml` |
| Ports | ✅ everything binds to 127.0.0.1; PostgreSQL on an internal network (published only by the dev override) |
| Unchanged controls | Authentication, CSRF (origin + token), rate limits, upload validation and size limits untouched. Production validation unchanged, apart from the new access-key length check. |

**Bug fixed (needs your awareness): httpx vs httpx2.** google-genai 3.0 sends requests through `httpx2`,
but `app/ai/gemini.py` imported and caught `httpx`, which only the dev requirements install. Consequences
before the fix:

1. **The production image could not start with a Gemini key** (`ModuleNotFoundError`).
2. Everywhere, real SDK timeouts and connection errors (`httpx2.*`) were not classified as timeouts or
   retryable, so they surfaced as generic failures without retries.

Tests passed because they injected `httpx` exceptions. The adapter now recognises both libraries; `httpx2`
is a pinned runtime dependency; regression tests cover both libraries and importing the app without `httpx`.
Live Gemini behaviour is still unverified ([gemini-verification-plan.md](gemini-verification-plan.md)).

**Proxy trust.** Per-IP login/registration limits now rely on `X-Forwarded-For`. That is sound only with
`BACKEND_ACCESS_KEY`, now mandatory in production: it guarantees requests came through Vercel, which documents that it overwrites
that header. Without the key, a direct caller could forge the header; per-email and per-user limits would
still hold.

## 12. Image sizes and the CJK font decision

| Variant | Size | CJK in PDFs |
|---|---|---|
| Default | 542 MB | 日本語 rendered as **empty boxes**; no CJK font embedded |
| `INSTALL_CJK_FONTS=true` | 712 MB (**+169 MB, +31%**; `fonts-noto-cjk` = 89 MB of font files) | Rendered correctly; `Noto-Sans-CJK-JP` subset embedded |

Evidence: the edge-case sample (`edge-cases-modern.pdf`) was rendered in both variants, its embedded fonts
were listed with pypdf, and both PDFs were inspected visually. In **both** variants the text layer contains
the correct characters, which helps text extraction, but **it does not fix the visual rendering**: without the
fonts, PDFs do not visually support CJK. The CJK
variant also increases that line's height by about 3 px (Noto's taller metrics).

**Decision (approved 2026-11-11): opt-in, off by default.** The application declares no CJK support (the scoring lexicon and
prompts are English), so a 31% larger image for every deploy is not justified by default. If resumes with
CJK names or text are expected, enable it on Render by adding `INSTALL_CJK_FONTS=true` as a Docker build
argument (dashboard), or flip the `ARG` default.

## 13. Not verified

| Item | Why | How to verify |
|---|---|---|
| Real Vercel behaviour (routes with `env`, header transform, SPA fallback, cookie pass-through, body size, proxy time limit) | No deployment authorized | [deploy-vercel.md §4](deploy-vercel.md#4-verify-after-deploying) on the first preview |
| Real Render behaviour (Blueprint apply, `preDeployCommand` in the Docker runtime, `$PORT`, health check, generated key) | No deployment authorized; Render CLI not available | [deploy-render.md §4](deploy-render.md#4-verify-after-deploying) |
| GitHub Actions runs | Nothing pushed | Push a branch / open a PR (your action) |
| Live Gemini calls (including the httpx2 fix against real timeouts) | Live calls not authorized | [gemini-verification-plan.md](gemini-verification-plan.md) |
| Vercel's overwriting of `X-Forwarded-For` | Documented by Vercel, not observed | Check `request` log IPs on Render after deploying |
| In-flight request during SIGTERM | Not exercised | Start a rewrite, redeploy, confirm it completes |
| arm64 images | Built on linux/amd64 only (Render builds amd64) | `docker buildx build --platform linux/arm64` |
| DOCX in Microsoft Word | Unchanged from Milestone 6 | [export-qa.md §4](export-qa.md) checklist |

## 14. Manual setup before deploying

1. ~~Approve M8-1 and M8-9~~ — approved 2026-11-11 (§16).
2. Render: create the Blueprint from `render.yaml`; enter `GEMINI_API_KEY` and `CORS_ORIGINS`; review the plan and region.
3. Vercel: project root `frontend`; set `BACKEND_URL` (Render URL) and `BACKEND_ACCESS_KEY` (copied from Render, marked Sensitive) for Production (and Preview if used).
4. Set `CORS_ORIGINS` on Render to the final Vercel/custom origins.
5. Optional: database backups (dashboard); switch `autoDeployTrigger` to `checksPass` once CI has run green.
6. Run the post-deploy checks in both guides; `scripts/smoke_test_stack.py <vercel-url> --no-ai`.

## 15. Confirmation

No deployment, Render/Vercel project creation, image push, `git add`, commit, push, branch switch or history
change took place. No live Gemini call was made. Containers, volumes and networks created for verification
were removed afterwards. The local images `resume-analyzer-api:local`, `resume-analyzer-api:fake-ai`,
`resume-analyzer-web:local` and `resume-analyzer-web:dev` remain for reuse (`docker rmi` to remove them).

## 16. Follow-up after review (2026-11-11)

| Approved item | Implemented | Verified |
|---|---|---|
| **Access key, fail closed.** Render generates it, Vercel stores it server-only, never in client code; constant-time compare; never logged; liveness the only unauthenticated exception; production refuses to start without it; disabled locally/tests unless exercised | `APP_ENV=production` now fails validation without `BACKEND_ACCESS_KEY` (blank counts as missing) or with < 32 characters. The exemption was narrowed from two paths to **one**: `/api/v1/health` (the legacy alias `/api/health` now needs the key like everything else). `render.yaml` unchanged (already `generateValue: true`). CI's production checks pass the key to `migrate` and assert the fail-closed message and the `/api/health` 403 | Unit/integration tests: fail closed (missing and blank), length, exemption list (`/api/health`, readiness, docs, unknown paths and `/api/v1/health/` all 403 without the key), key never in logs or responses, disabled by default. Production image: exits 1 with the message when the key is absent; the CI image-check step re-run locally passes |
| **CJK stays opt-in** | `INSTALL_CJK_FONTS=false` unchanged; docs now state plainly that without the fonts PDFs do **not** visually support CJK and that the text layer does not solve that | Wording reviewed in `export-qa.md`, `rewriting.md`, `deploy-docker.md`, this report |
| **Test timeout 5 → 10 s** | `frontend/src/pages/Rewrite.test.jsx`, that one test only; assertions unchanged | 23/23 in the file; full results below |

**Results after the follow-up (final code; these supersede §6 where they differ):**

| Check | Result |
|---|---|
| ruff, format, strict mypy | ✅ clean |
| Backend, SQLite | ✅ 809 passed, 1 skipped (PostgreSQL-only lock test) |
| Backend, PostgreSQL 16.15 | ✅ 810 passed |
| Frontend `npm run check` | ✅ 97/97 |
| Playwright (default mode) | ✅ 16/16 |
| `render.yaml`, `vercel.json` schemas; `actionlint` | ✅ |
| Production image without `BACKEND_ACCESS_KEY` | ✅ exits 1 with the fail-closed message; CI image-check step passes locally |

The Compose stacks were not re-run after the follow-up: they run with `APP_ENV=development`, where the key
stays disabled, and their code paths are unchanged.
