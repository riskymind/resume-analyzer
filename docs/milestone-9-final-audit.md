# Milestone 9 — Final Repository Audit

_Date: 2026-11-11 · audience: the project owner and developers preparing the first deployment. Results of the
verification runs are in [milestone-9-final-report.md](milestone-9-final-report.md). Nothing was deployed,
staged, committed or pushed, and no live Gemini call was made._

## 1. Repository state

| Item | Finding |
|---|---|
| Branch / HEAD | `main` at `ac8d085` ("Merge pull request #5 … feature/ui-redesign"), the same commit as the Milestone 1 baseline |
| Working tree | **All work from Milestones 1–9 is uncommitted.** `git diff --stat` shows 27 tracked files changed (+8 152 / −1 483); 84 untracked paths (the whole `backend/app/`, `backend/tests/`, `docs/`, `.github/`, the TypeScript frontend, Docker, Compose and deployment files). The pre-refactor files (`backend/database.py`, `backend/routes/`, `frontend/src/*.jsx`, `AGENTS.md`, `test.txt`, …) show as deleted |
| Consequence | Render (Blueprint) and Vercel build from the GitHub repository, so **nothing can be deployed, and GitHub Actions cannot run, until the work is committed and pushed** (your decision; not done here) |
| Secrets in the tree | `/.env` and `backend/.env` exist locally. Both are git-ignored (`.gitignore` lines 8 and 10) and excluded from both Docker build contexts (`.dockerignore`). Only variable names were inspected, not values. No key-shaped strings (`AIza…`, `sk-…`) in any manifest, example or Compose file |
| Local data | `resume_analyzer.db` (repository root, ignored) and `backend/data/` (ignored) are pre-refactor/local data; neither reaches an image |

## 2. Architecture as built

```
Browser ── HTTPS ──► Vercel: static SPA (frontend/dist)
                       └─ routes: /api/(.*) → ${BACKEND_URL}/api/$1  + x-backend-access-key (server-side)
                                   │
                                   ▼
                     Render: Docker web service (backend/Dockerfile)
                       FastAPI app.main:app, uvicorn, non-root uid 10001, binds $PORT
                       BackendAccessKeyMiddleware (only /api/v1/health exempt)
                       preDeployCommand: python -m app.cli migrate (advisory-locked)
                                   │                         │
                                   ▼                         ▼
                     Render PostgreSQL 16          Gemini API (google-genai 3.0.0, server-side key)
```

| Layer | Location | Notes |
|---|---|---|
| API / controllers | `backend/app/api/` | Thin routers under `/api/v1`; legacy `/api/analyze`, `/api/analyses` kept (M7-7) |
| Services | `backend/app/services/` | Auth, resumes, scoring, job extraction, matching, rewriting + verification |
| AI | `backend/app/ai/` | Only `gemini.py` imports the SDK; prompts fence untrusted text; structured output schemas |
| Parsing | `backend/app/parsing/` | PDF, DOCX, Markdown; size, magic bytes, MIME, encryption checks |
| Documents | `backend/app/documents/` | Five templates; one definition drives preview HTML, WeasyPrint PDF, python-docx DOCX |
| Persistence | `backend/app/db/`, `backend/app/repositories/` | SQLAlchemy 2, Alembic (6 revisions, head `0006`), 15 tables; SQLite locally, PostgreSQL in production |
| Core | `backend/app/core/` | Settings (fail-fast production validation), JSON logging, error envelope, middleware, security |
| Frontend | `frontend/src/` | React 18 + TypeScript 5.9, react-router 7, Vite 6; relative `/api` base; generated API types |
| Delivery | `backend/Dockerfile`, `frontend/Dockerfile`, `compose*.yaml`, `render.yaml`, `frontend/vercel.json`, `.github/workflows/` | — |

The documented architecture ([deployment-architecture.md](deployment-architecture.md), the three deployment
guides) matches the code, with the stale passages listed in §4, which are now corrected.

## 3. Configuration cross-checks

| Check | Method | Result |
|---|---|---|
| Every `Settings` field documented | Compared `Settings.model_fields` with `backend/.env.example` | ✅ none missing, none extra (container-only `PORT`, `WEB_CONCURRENCY`, `FORWARDED_ALLOW_IPS`, `RUN_MIGRATIONS_ON_START`, `GRACEFUL_SHUTDOWN_SECONDS` are documented as such) |
| Variable names in docs | Every back-quoted UPPER_CASE name in README, deployment docs, `render.yaml`, `.env.example` checked against `Settings`, Compose and frontend variables | ✅ one stale name: `JWT_SECRET` (§4) |
| Health-check path | `backend/Dockerfile` `HEALTHCHECK`, `render.yaml` `healthCheckPath`, middleware exemption, guides | ✅ all `/api/v1/health` |
| Ports | Dockerfiles, Compose, guides | ✅ API 8000 (`$PORT` on Render), web 8080, dev 5173 / 8000 / 5433, fake-AI 8090; all host ports on 127.0.0.1 |
| Migration commands | `render.yaml`, Compose `migrate`, entrypoint, guides, CI | ✅ all `python -m app.cli migrate` |
| Access key | `config.py`, middleware, `render.yaml` (`generateValue: true`), `vercel.json` (header transform), guides | ✅ consistent; only `/api/v1/health` exempt; `/api/health` not exempt |
| Vercel variables | `vercel.json` `env` lists vs guide | ✅ `BACKEND_URL`, `BACKEND_ACCESS_KEY`, both server-side; no `VITE_*` |
| Fake AI never in production | `render.yaml` image/target, `mock_ai_server.py` refusal, Compose override | ✅ Render builds the default (`production`) target; the fake server refuses `APP_ENV=production`; the fake override is a separate project |
| Links in README and `docs/*.md` | Script resolving every relative link | ✅ no broken links |
| Node / Python versions | Workflows, Dockerfiles, guides | ✅ Node 24 everywhere. Python: CI and image 3.12, `pyproject.toml` declares ≥ 3.11; this machine's tests ran on 3.13. **3.11 itself has not been tested** |

## 4. Defects found and fixed in this milestone

| # | Defect | Fix |
|---|---|---|
| F1 | README told developers to run `mypy app tests`, which failed with 36 errors in `tests/integration/test_deployment.py` (added in Milestone 8). CI ran `mypy app scripts`, so nothing caught it | Annotated the two `base` dictionaries `dict[str, Any]` (typing only; no assertion changed). `mypy app tests scripts` is now clean, and `backend.yml` runs exactly that |
| F2 | `deployment-architecture.md` still described the planned design in places: `node:22-alpine`, `python:3.12-slim`, "+50 MB" CJK fonts (measured: +169 MB), an entrypoint running `alembic upgrade head`, a `JWT_SECRET` startup check (sessions are server-side; there is none), an optional Render static site, a MinIO/S3 storage row | Corrected to the as-built configuration |
| F3 | `refactoring-plan.md` header said "proposed — awaiting decisions", and §6 described a retention purge that does not exist | Status updated; retention marked not implemented; Milestone 9 row and decision record added |
| F4 | README said "Full documentation lands in the final milestone"; it had no architecture overview, limitations or verification caveats | README rewritten (existing content preserved or linked) |
| F5 | The local Playwright command fails on machines where `python` is not on `PATH` (it starts the fake API with `python`) | Documented `E2E_PYTHON=../backend/venv/bin/python` in the README (the variable already existed in `playwright.config.ts`) |

## 5. Defects found and **not** fixed (need a decision)

| # | Finding | Impact | Proposed fix |
|---|---|---|---|
| N1 | **✅ Fixed after approval (2026-11-11; [final report §21](milestone-9-final-report.md#21-follow-up-pdf-resource-fetcher-fix-approved-2026-11-11)).** **WeasyPrint 70 is incompatible with the plain-function `url_fetcher`** (`app/documents/render.py:157`). When the fetcher refuses a URL, WeasyPrint's error path reads `url_fetcher._fail_on_errors`, which a function does not have, so rendering aborts with `AttributeError` instead of skipping the resource | **Security is intact.** Probed in the production image with hostile HTML (external stylesheet, `@import`, `@font-face`, images, iframe, object, `file:///etc/passwd`): 0 connection attempts, no file read. **No current trigger:** the template contains no fetchable reference (only escaped `<a href>` links, which are never fetched), and user text is escaped, so real exports never reach this path (123 export tests pass in the container). If a template ever referenced an asset, PDF export would fail with a 500 instead of degrading | Pass a `weasyprint.URLFetcher` subclass whose `fetch` raises (or the library's own refusal mechanism), and add an end-to-end test that renders hostile HTML through `render_pdf`. It is a change to a security boundary, so it was not made without approval |
| N2 | `backend.yml` uses `actions/*@v4/@v5` tags, not commit SHAs | Standard practice, slightly weaker supply-chain guarantee | Optional: pin by SHA and add Dependabot for actions |
| N3 | No Dependabot / Renovate configuration | New advisories are found only when someone runs `pip-audit` / `npm audit` (CI runs both on every push) | Add `.github/dependabot.yml` (pip, npm, docker, github-actions) |
| N4 | With a root `.env` containing `GEMINI_API_KEY`, the fake-AI Compose override blanks the key for `api` but `migrate` still receives it | Harmless (migrations never call AI); noted for completeness | Optional: blank it for `migrate` in `compose.fake-ai.yaml` too |

## 6. Specific checks requested by the brief

| Check | Result |
|---|---|
| Stale instructions / removed files / removed commands | Fixed (§4). No references to removed files |
| Incorrect environment variable names | One (`JWT_SECRET`), fixed |
| Incorrect ports or health-check paths | None |
| Inconsistent API URLs | None: the browser uses relative `/api`; `BACKEND_URL` is origin-only in every guide |
| Incorrect migration instructions | None |
| Contradictory production / development instructions | None found; the reason Compose runs `APP_ENV=development` is explained consistently ([deploy-docker.md §4](deploy-docker.md#4-why-the-compose-api-runs-with-app_envdevelopment)) |
| Secrets committed or in build contexts | None (§1) |
| Mock AI enabled in production | Not possible (§3) |
| Claims about provider verification | Reviewed. Milestone 8 documents state clearly that Vercel, Render, GitHub Actions and live Gemini were not exercised. [gemini-verification-plan.md](gemini-verification-plan.md) distinguishes superseded-schema results from final-schema results. Its Milestone 9 status note makes one point explicit: the adapter code **after** the Milestone 8 `httpx2` change has never made a live call |
