# Resume Analyzer

Upload a resume (PDF, DOCX or Markdown) and get a job-independent quality score and an ATS readability score,
both calculated by fixed, documented rules. Paste a job description to get an evidence-based match report
with skill gaps. Then let the AI propose a tailored rewrite, in which every change is checked against your
original resume. Review and edit the rewrite and download it as PDF or DOCX in one of five templates.

Scores are calculated by application code, never by the AI, and an ATS score is an estimate of how well a
parser can read the document. It does not predict a screening or hiring outcome.

> **Status (2026-11-11):** feature-complete and verified locally ([final report](docs/milestone-9-final-report.md)).
> **Not yet deployed.** It has not run on Vercel or Render, in GitHub Actions, or against the live Gemini API
> for the rewrite feature. See [Current limitations](#current-limitations-and-verification-caveats).

## Capabilities

| Area | What it does | Details |
|---|---|---|
| Accounts | Email + password (Argon2id), server-side sessions in an `HttpOnly` cookie, CSRF protection, per-user data isolation, account deletion | [docs/auth.md](docs/auth.md) |
| Resume analysis | Validates the file (size, signature, MIME, encryption), extracts text, has the AI extract a structure that is verified against the text, and scores it deterministically (overall, ATS, sections, strengths, weaknesses, recommendations) | [docs/scoring-methodology.md](docs/scoring-methodology.md) |
| Job matching | Extracts requirements from a pasted or uploaded job description, then scores the match deterministically: lexicon, related skills, cached semantic similarity, gap analysis | [docs/job-matching-methodology.md](docs/job-matching-methodology.md) |
| AI rewriter | Four modes (ATS, professional, job-specific, executive), whole-resume or per-section regeneration, accept/reject, manual edits, versions and restore, before/after scores. Employers, titles, dates, degrees and certifications are copied by code, never written by the AI, and new numbers or skills are blocked | [docs/rewriting.md](docs/rewriting.md) |
| Export | Five templates (Modern professional, Minimalist, Traditional corporate, Technical, Graduate), HTML preview, PDF (WeasyPrint) and DOCX (python-docx), generated on demand and never stored. Exporting content that is not verified needs an explicit acknowledgement | [docs/export-qa.md](docs/export-qa.md) |
| Frontend | Dashboard, drag-and-drop upload with progress, analysis, matching, rewrite editor with diff, preview and downloads; keyboard-accessible, responsive | [docs/frontend.md](docs/frontend.md) |

## Architecture

```
Browser ──► Vercel (static React SPA)
              └─ /api/* proxied server-side to Render, adding X-Backend-Access-Key
                    ▼
            Render: FastAPI in Docker (non-root) ──► Render PostgreSQL 16
                    └──► Gemini API (server-side key only)
```

The browser only ever talks to the frontend origin and calls the relative path `/api`. The backend URL,
access key and AI key are never in the bundle. Locally, nginx (Docker) or Vite (dev) plays the proxy's role.
Design and rationale: [docs/deployment-architecture.md](docs/deployment-architecture.md). Code layout:
`backend/app/{api,services,ai,parsing,documents,db,repositories,core}`, `frontend/src/{pages,components,api,auth}`.

**Stack.** Python 3.12 (≥ 3.11 declared), FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2, google-genai,
WeasyPrint, python-docx · React 18, TypeScript 5.9, react-router 7, Vite 6, Vitest, Playwright · PostgreSQL 16
(SQLite for local development and tests) · Docker, nginx, Render, Vercel, GitHub Actions.

## Prerequisites

- **Docker route:** Docker with Compose v2 (tested with Docker 29.8 / Compose 5.5).
- **Without Docker:** Python 3.12 (3.13 also used locally; 3.11 is declared but untested), Node 24, and for
  PDF export the Pango library (`brew install pango` on macOS; Debian packages in
  [export-qa.md §5](docs/export-qa.md#5-system-packages-linux--docker)).
- A Gemini API key **only** for real AI features. Tests and the fake-AI modes need none.

## Run with Docker (quickest)

```bash
cp .env.example .env            # set POSTGRES_PASSWORD (openssl rand -hex 16); GEMINI_API_KEY is optional
docker compose up --build       # production-like stack: http://localhost:8080 (nginx → API → PostgreSQL)
docker compose down             # stop; data is kept. `docker compose down --volumes` deletes it
```

Without `GEMINI_API_KEY`, everything except the AI actions works, and those answer "AI analysis is not
configured". **With** a key, the stack makes real, billable Gemini calls.

- Development with hot reload: `docker compose -f compose.yaml -f compose.dev.yaml up --build` (http://localhost:5173).
- Isolated run with the fake AI provider (no key, no credits) on http://localhost:8090:
  [deploy-docker.md](docs/deploy-docker.md#isolated-fake-ai-run-no-credentials-no-ai-credits).

## Run without Docker

```bash
# Backend: http://localhost:8000 (API docs at /api/docs in development)
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env               # set GEMINI_API_KEY for real AI features
uvicorn app.main:app --reload      # `uvicorn main:app` also still works

# Frontend: http://localhost:5173, proxies /api to the backend (override with API_PROXY_TARGET)
cd frontend
npm ci
npm run dev
```

The SQLite database is created and migrated automatically at `backend/data/resume_analyzer.db`.

- **Upgrading from the pre-refactor version?** The database used to live at the repository root. To keep your
  history: `mv resume_analyzer.db backend/data/resume_analyzer.db` (the server logs a reminder if it finds the
  old file). History created before accounts existed stays hidden until you assign it:
  `python -m app.cli assign-history --email you@example.com` (backup and rollback included; [auth.md](docs/auth.md)).
- **No AI key? Use the fake provider:** `cd backend && python -m scripts.mock_ai_server` starts the API on :8000
  with the test suite's canned AI answers (it refuses `APP_ENV=production` and never reads `GEMINI_API_KEY`).
  Upload `frontend/e2e/fixtures/jane-doe-resume.md` and paste `frontend/e2e/fixtures/job.txt`.
- **PDF export** needs Pango. Without it, PDF returns `503 export_unavailable` and DOCX still works. On an
  Intel Mac with old Command Line Tools, Homebrew may compile from source (30–40 minutes). macOS lacks
  Carlito/Caladea, so local PDFs use fallback fonts; production PDFs are rendered in the Linux image.
  `python -m scripts.render_export_samples <dir>` writes every template as DOCX, PDF and HTML.

## Configuration

| File | For |
|---|---|
| [.env.example](.env.example) | Docker Compose (copy to `.env`): `POSTGRES_PASSWORD` (required), optional `GEMINI_API_KEY`, ports |
| [backend/.env.example](backend/.env.example) | Every backend setting, documented (limits, timeouts, AI, sessions, rate limits, access key) |
| Render dashboard | `GEMINI_API_KEY`, `CORS_ORIGINS` (entered); `BACKEND_ACCESS_KEY` (generated); the rest is in `render.yaml` ([deploy-render.md](docs/deploy-render.md#1-environment-variables)) |
| Vercel project | `BACKEND_URL`, `BACKEND_ACCESS_KEY`. Both are **server-side only**; there are no `VITE_*` variables ([deploy-vercel.md](docs/deploy-vercel.md#2-environment-variables)) |

With `APP_ENV=production` the API refuses to start, listing each problem without its value, unless it has
PostgreSQL, HTTPS-only `CORS_ORIGINS`, secure cookies, a Gemini key and a `BACKEND_ACCESS_KEY` of at least 32
characters. Never put a secret in a `VITE_*` variable: those are compiled into public JavaScript.

## API overview

All endpoints are under `/api/v1`, return a JSON error envelope `{"error": {"code", "message", "request_id"}}`
and require a session, except registration, login and health. State-changing requests need a trusted
`Origin` and the `X-CSRF-Token` header. Interactive docs: `/api/docs` (development only).

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `DELETE /auth/me` (delete the account and all its data) |
| Resumes | `POST /resumes` (multipart `file`), `GET /resumes`, `GET`/`DELETE /resumes/{id}`, `GET /resumes/{id}/document` |
| Jobs | `POST /jobs` (`text` or `file`), `GET /jobs`, `GET`/`DELETE /jobs/{id}`, `POST /jobs/{id}/extraction` (re-extract) |
| Matches | `POST /matches` `{resume_id, job_id}`, `GET /matches[?job_id=&resume_id=]`, `GET`/`DELETE /matches/{id}` |
| Rewrites | `POST /rewrites` `{resume_id, job_id?, scope, mode?}`, `GET /rewrites`, `GET`/`PATCH`/`DELETE /rewrites/{id}` (review, edit, accept/reject, restore a version), `POST /rewrites/{id}/regenerate`, `GET /rewrites/{id}/preview`, `GET /rewrites/templates`, `POST /rewrites/{id}/export` (PDF/DOCX) |
| Health | `GET /health` (liveness; the only path exempt from the production access key), `GET /health/ready` (database + AI configured) |
| Legacy (outside `/api/v1`) | `POST /api/analyze`, `GET /api/analyses[/{id}]` (original contract kept; `score` is now the deterministic match percentage); `GET /api/health[/ready]` (aliases; they need the access key in production) |

The exact contract is the generated OpenAPI schema [frontend/openapi.json](frontend/openapi.json), from which
the frontend's types are generated (`npm run types:generate`; CI fails on drift).

## Tests and quality checks

Tests never call the real AI provider and never spend credits.

```bash
# Backend (from backend/, venv active)
ruff check . && ruff format --check .
mypy app tests scripts                     # strict
pytest                                     # SQLite: 820 passed, 1 skipped (PostgreSQL-only lock test)
TEST_DATABASE_URL=postgresql://user:pw@localhost:5432/test pytest   # PostgreSQL: 821 passed
pip-audit -r requirements.txt --strict

# Frontend (from frontend/)
npm ci
npm run check        # typecheck, ESLint, Prettier, Vitest (97 tests), production build
npm audit
E2E_PYTHON=../backend/venv/bin/python npm run test:e2e   # Playwright journey (fake AI; uses local Chrome)

# Containers (from the repository root): fake-AI stack + smoke test + browser journey
docker compose -p resume-analyzer-fakeai -f compose.yaml -f compose.fake-ai.yaml up --build -d --wait
python3 -I scripts/smoke_test_stack.py http://localhost:8090
(cd frontend && E2E_BASE_URL=http://localhost:8090 npx playwright test)
docker compose -p resume-analyzer-fakeai -f compose.yaml -f compose.fake-ai.yaml down --volumes
```

PDF tests are skipped when Pango is missing. CI (`.github/workflows/`) runs all of the above: `backend.yml`
(lint, types, `pip-audit`, SQLite and PostgreSQL suites, migration round trip), `frontend.yml` (checks,
`npm audit`, Playwright, OpenAPI drift), and `docker.yml` (manifest schemas, image builds, production-mode
start-up and access-key checks, the fake-AI stack, smoke test, Playwright, log scan). There are no deploy
steps and no secrets.

## Deployment

Frontend on **Vercel**, API on **Render** (Docker) with **PostgreSQL**. Nothing deploys automatically (Render
`autoDeployTrigger: "off"`, no deploy jobs in CI).

| Guide | Covers |
|---|---|
| [docs/deploy-render.md](docs/deploy-render.md) | `render.yaml` Blueprint, environment variables, migrations (pre-deploy, advisory-locked), post-deploy checks |
| [docs/deploy-vercel.md](docs/deploy-vercel.md) | `frontend/vercel.json` routing (API proxy with injected key, SPA fallback), server-only variables, post-deploy checks |
| [docs/deploy-docker.md](docs/deploy-docker.md) | Images, Compose stacks, commands, troubleshooting |
| [First-deployment checklist](docs/milestone-9-final-report.md#18-first-deployment-checklist) | The order of the manual steps, and what to verify before real users |

## Current limitations and verification caveats

- **Not deployed and never run on Vercel or Render.** Their behaviour has been checked against their
  published schemas and emulated locally, but not observed on the real platforms.
- **GitHub Actions have never run.** All work is uncommitted; the workflows are validated locally only.
- **Live Gemini is largely unverified.** Only resume extraction (G1) passed live with the final schema. Job
  extraction failed once with an earlier schema, and the rewrite, prompt-injection and timeout scenarios have
  never run against the real model ([gemini-verification-plan.md §4](docs/gemini-verification-plan.md#4-status-at-milestone-9-2026-11-11-no-live-calls-made)).
  In the one live run, Gemini answered 14 of 26 requests with 503 (overloaded).
- **DOCX files have not been opened in Microsoft Word**; there is only a manual checklist ([export-qa.md §4](docs/export-qa.md#4-docx-what-is-and-is-not-verified)).
- **CJK text** renders as empty boxes in PDFs unless the image is built with `INSTALL_CJK_FONTS=true` (+169 MB).
- **No password reset** (no e-mail delivery), **no automatic data-retention purge** (users delete their own
  data), and **no monitoring/alerting** beyond the platform log stream.
- Accessibility is checked automatically (lint rules, keyboard and layout tests), not yet by a person using
  assistive technology.

Full list with priorities: [milestone-9-final-report.md §17](docs/milestone-9-final-report.md#17-prioritised-production-readiness-issues).

## Security

Uploaded resumes and job descriptions are treated as untrusted data: they are fenced in prompts, and every AI
output is verified by code. Files are validated by signature, not extension. Originals are never stored.
PDF rendering cannot fetch external resources. Logs never contain resume text, tokens or passwords. Rate
limits apply to login, registration and AI usage. In production the API accepts only requests carrying the
proxy's access key. Review details: [milestone-9-final-report.md §11](docs/milestone-9-final-report.md#11-security-review).
