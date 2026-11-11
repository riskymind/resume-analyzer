# Refactoring & Implementation Plan

_Companion to [architecture-audit.md](architecture-audit.md). Status: **Milestones 1–9 complete** (§8). The
§2 decisions were taken with the recommended options. Sections 3–7 are the original plan; where the build
differs, the decision records (§10–§15) and the topic documents describe what exists. Final verification and
open issues: [milestone-9-final-report.md](milestone-9-final-report.md)._

## 1. Principles

- **Evolve, don't replace.** Keep FastAPI, React + Vite, Gemini, and the existing visual identity.
- The app must stay runnable after every milestone. Each milestone is a separate branch/PR
  (`feature/<desc>`) per repo conventions. Nothing is committed without authorization.
- Numbers come from deterministic code; the LLM extracts, explains, and rewrites.
- Resume and JD content is **untrusted data**, never instructions.
- Rewrites must be fact-preserving, verified by code rather than just by prompt.
- Don't overengineer. No microservices, no queue unless timeouts force one.

## 2. Decisions requiring your input

These change what gets built. The recommendations are marked; I'll proceed with them unless you say
otherwise.

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | **Authentication** (required for user profiles and data isolation) | (a) Built-in email + password: argon2 hashes, JWT in an httpOnly cookie. (b) External provider (Clerk / Auth0 / Supabase Auth). (c) Anonymous per-browser workspace token, no accounts. | **(a)**: no third-party account, works identically in Docker, Render and Vercel. Password reset by email is out of scope initially (it needs an SMTP provider). |
| D2 | **Production database** | Keep SQLite (needs a Render persistent disk, single instance, impossible on Vercel) vs PostgreSQL | **PostgreSQL in production** (Render Postgres or Neon) via SQLAlchemy 2 + Alembic. **SQLite stays the zero-config default for local dev and tests.** |
| D3 | **File storage** | (a) Persist original uploads in S3-compatible storage (R2/S3/MinIO). (b) Don't persist originals; keep extracted text + structured data and generate exports on demand. | **(b) by default**: less PII at rest, no storage credentials. A `StorageBackend` interface (local volume / S3) is still built and used for optional original-file retention, gated by `STORE_ORIGINAL_UPLOADS`. |
| D4 | **Hosting topology** | (a) Vercel frontend + Render API. (b) FastAPI as Vercel Python Functions. (c) Everything on Render. | **(a)**, with Vercel rewrites `/api/*` → Render so the browser stays same-origin (cookies, no CORS). Docker Compose runs the same images locally. Rationale in [deployment-architecture.md](deployment-architecture.md). |
| D5 | **PDF engine** | WeasyPrint (HTML/CSS templates, best typography, needs Pango system libs) vs ReportLab (pure Python, layout in code) | **WeasyPrint**: one Jinja HTML template per design drives both the browser preview and the PDF. This requires the API to run from Docker on Render (already the plan in D4). DOCX via `python-docx`. |
| D6 | **Frontend typing / routing** | Stay JS vs migrate to TypeScript; tabs vs `react-router` | **Migrate to TypeScript incrementally** (strict, `allowJs` during transition) and add `react-router`. |
| D7 | **Semantic similarity** | Gemini embeddings API vs local `sentence-transformers` (+~1 GB image) vs none | **Gemini embeddings** with an in-DB cache. If the embedding call fails, matching degrades to deterministic-only and the response says so. |

## 3. Target backend structure

```
backend/
├── app/
│   ├── main.py                 # create_app(): lifespan, middleware, routers, exception handlers
│   ├── core/
│   │   ├── config.py           # pydantic-settings; validates required env at startup
│   │   ├── logging.py          # structured JSON logs, request-id, PII redaction
│   │   ├── errors.py           # AppError hierarchy → {"error":{"code","message","request_id"}}
│   │   ├── security.py         # password hashing, JWT, cookie helpers
│   │   └── rate_limit.py       # per-user / per-IP limits (slowapi; Redis optional)
│   ├── api/                    # thin routers, Pydantic in/out
│   │   ├── deps.py             # get_db, get_current_user, get_ai_client (DI)
│   │   ├── auth.py  resumes.py  analyses.py  jobs.py  matches.py  rewrites.py  exports.py  health.py
│   ├── schemas/                # Pydantic request/response + domain models (StructuredResume, JobProfile…)
│   ├── services/               # business logic, no FastAPI imports
│   │   ├── resume_service.py   analysis_service.py  matching_service.py
│   │   ├── rewrite_service.py  export_service.py
│   │   └── scoring/            # deterministic scorers (ats.py, sections.py, readability.py, keywords.py)
│   ├── ai/
│   │   ├── client.py           # AIClient protocol + GeminiClient (google-genai), timeouts, retries
│   │   ├── prompts/            # versioned prompt templates with untrusted-data fencing
│   │   └── guards.py           # output schema validation + fact-preservation checks
│   ├── parsing/
│   │   ├── validation.py       # size (streamed), magic bytes, MIME, encryption, page limits
│   │   ├── pdf.py  docx.py  markdown.py
│   ├── documents/
│   │   ├── templates/          # 5 Jinja HTML templates + shared CSS
│   │   ├── pdf_renderer.py     # WeasyPrint
│   │   └── docx_renderer.py    # python-docx
│   ├── storage/                # StorageBackend: LocalStorage, S3Storage
│   └── db/
│       ├── session.py  models.py  repositories/
│       └── migrations/         # Alembic
├── tests/  (unit/ integration/ security/  + fixtures/ with sample PDFs/DOCX)
├── pyproject.toml              # ruff, mypy, pytest config
└── requirements.txt / requirements-dev.txt
```

The move from `backend/*.py` to `backend/app/` is done once, in Milestone 2, with behaviour preserved
and covered by tests written *before* the move.

## 4. Scoring methodology (transparent, deterministic first)

The LLM produces **structured facts** (extracted fields, requirement lists, qualitative notes). All
**numbers** are computed in `services/scoring/` from those facts plus the raw text, so the same input
always gives the same score. Every score ships with its component breakdown.

**Resume analysis.** The overall score is a weighted sum of section scores:

| Component | Weight | Deterministic signals |
|---|---|---|
| Structure | 15 | Presence/order of core sections, contact info completeness |
| Summary | 10 | Present, length band, specificity (non-generic phrase ratio) |
| Experience | 25 | Bullet count per role, action-verb ratio, tense consistency, dates parseable |
| Achievements | 15 | Share of bullets with quantified outcomes (numbers in *source* text) |
| Skills | 10 | Count, categorisation, duplication |
| Formatting / ATS | 15 | Text extractable, no tables/columns heuristics, standard headings, length, special chars |
| Readability | 10 | Sentence length, Flesch-style score, passive-voice ratio |

**ATS compatibility** is its own 0–100 score from the formatting and parseability signals. The UI
carries an explicit disclaimer that it estimates parseability and guarantees no screening outcome.

**Job match %:** superseded during Milestone 4 by the implemented methodology in
[job-matching-methodology.md](job-matching-methodology.md) (seven components, importance-weighted
requirements, mandatory-gap caps, related matches at 0.35 credit). The LLM extracts requirements and
never emits the percentage.

## 5. AI integrity controls (rewriter)

1. **Prompt fencing.** Untrusted text is wrapped in delimited blocks, with system instructions stating
   that the content is data. Injected instructions are logged as a signal.
2. **Structured I/O.** The rewrite input is the `StructuredResume` JSON, and the output must validate
   against the same schema (`response_schema` in google-genai).
3. **Post-generation fact guard** (`ai/guards.py`, deterministic):
   - Employers, job titles, dates, degrees, institutions and certifications must match the source
     exactly (normalised). Any mismatch rejects the rewrite, or that section is reverted.
   - Every number in the output must appear in the source section. A new metric is stripped and
     flagged.
   - Output skills must be a subset of source skills ∪ skills evidenced in source text. New ones go to
     the **gaps** list instead.
4. JD requirements absent from the resume are returned as `gaps[]`, never written into the resume.
5. Every rewrite is versioned (`rewrites` → `rewrite_sections`). Section regeneration creates a new
   section version. The UI diff compares original vs current.

## 6. Data model (target)

All tables have `id` (UUID), `created_at` and `updated_at` (UTC), and the user-owned ones have
`user_id` FK + index. Every repository query is scoped by `user_id`.

`users` · `resumes` (filename, mime, sha256, extracted_text, structured_json, storage_key nullable) ·
`resume_analyses` (scores_json, findings_json, model, prompt_version) · `job_descriptions`
(raw_text, profile_json) · `job_matches` · `rewrites` (mode, status) · `rewrite_sections` (section,
version, content_json) · `exports` (format, template, size, created_at; files streamed, not stored) ·
`embeddings_cache`.

**Legacy migration.** The existing `analyses` table is migrated by Alembic into `resumes` +
`job_descriptions` + `job_matches` (score → match %, recommendations preserved). Rows are attached to
a `legacy` local user so existing history is not lost.

**Retention.** `DELETE /api/me` and per-item deletes. A configurable `DATA_RETENTION_DAYS` purge runs
at startup and as a Render cron job. _As built: account and per-item deletion exist. The automatic
retention purge was **not implemented** (no `DATA_RETENTION_DAYS`, no purge command, no cron job; only expired
sessions and rate-limit counters are purged at start-up). Tracked as issue P1-6 in the Milestone 9 report._

## 7. API (target, all under `/api/v1`, JSON error envelope)

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `DELETE /auth/me` |
| Resumes | `POST /resumes` (upload + extract) · `GET /resumes` · `GET /resumes/{id}` · `PATCH /resumes/{id}` (edit structured data) · `DELETE /resumes/{id}` |
| Analysis | `POST /resumes/{id}/analyses` · `GET /analyses` · `GET /analyses/{id}` |
| Jobs | `POST /jobs` (paste or file → profile) · `GET /jobs/{id}` |
| Matching | `POST /matches` {resume_id, job_id} · `GET /matches` · `GET /matches/{id}` |
| Rewriter | `POST /rewrites` {resume_id, job_id?, mode} · `GET /rewrites/{id}` · `PATCH /rewrites/{id}/sections/{key}` (manual edit) · `POST /rewrites/{id}/sections/{key}/regenerate` |
| Export | `POST /rewrites/{id}/export` {format: pdf\|docx, template} → streamed attachment |
| Meta | `GET /health` (liveness) · `GET /health/ready` (DB + config) · `GET /templates` |

The legacy `POST /api/analyze` and `GET /api/analyses[/{id}]` stay as compatibility shims until the
new frontend replaces them, then they are removed in a later, explicit change.

## 8. Milestone plan

| M | Scope | Exit criteria |
|---|---|---|
| **1** | Audit + plans | ✅ This document set |
| **2** | Characterisation tests for current behaviour → move to `app/` layout; `pydantic-settings` config; structured logging; error envelope; lifespan; fix blocking event loop (`run_in_threadpool` / async client); LLM timeout; streamed size limit + magic bytes; upgrade vulnerable deps; `google-genai` migration; SQLAlchemy + Alembic (SQLite) with legacy migration; ruff + mypy + pytest | Existing flow works unchanged; tests green; `pip-audit` clean |
| **2b** | Auth (D1), user scoping, rate limiting, delete endpoints | Cross-user access tests pass |
| **3** | DOCX parsing, encrypted/malformed handling, structured extraction, deterministic scorers, analysis API | Parser fixtures + scorer unit tests |
| **4** | JD extraction, skill normalisation, embeddings + cache, match engine, gap analysis | Golden-file match tests |
| **5** | Rewriter: 4 modes, fact guard, section regenerate, versioning, diff data | Guard tests incl. fabricated-employer / fake-metric cases |
| **6** | 5 templates, WeasyPrint PDF, python-docx DOCX, preview endpoint, streamed downloads; export acknowledgement; job detachment; Vitest + Testing Library; browser, PDF/DOCX and dependency QA | ✅ Delivered (see §12). Manual Word check and live Gemini checks outstanding |
| **7** | TS migration, router, Dashboard / Upload (drag-drop, progress) / Analysis / Matching / Rewriter (editor, diff, regenerate, templates, preview, download); a11y; Vitest + Testing Library | ✅ Delivered (see §13 and [frontend.md](frontend.md)). CI workflow written but not yet run on GitHub |
| **8** | Dockerfiles, Compose (dev + prod-like profiles), `render.yaml`, `vercel.json`, GitHub Actions (no deploy) | ✅ Delivered (see §14 and [milestone-8-completion-report.md](milestone-8-completion-report.md)). Nothing deployed; GitHub Actions not yet run on GitHub; Vercel/Render behaviour verified only by configuration checks |
| **9** | Full verification run, README + deploy docs, final report | ✅ Delivered (see §15 and [milestone-9-final-report.md](milestone-9-final-report.md)). Every exit criterion met locally. External items (Vercel, Render, GitHub-hosted CI, live Gemini, Word, human a11y review) remain open and are listed as issues |

## 9. Risks

- **LLM latency vs request timeouts.** Rewrite of a full resume may take 20–60 s. It stays within
  Render limits and avoids Vercel's limits because the API is not on Vercel. If it becomes a problem,
  the fallback is a background task + polling endpoint (the DB `status` column is designed in from
  the start).
- **Gemini model availability.** `gemini-3.6-flash` is configured, not hardcoded (`GEMINI_MODEL`).
  It is not verified against the live API in this audit.
- **Extraction quality on complex PDF layouts** (multi-column, image-only). Image-only PDFs are
  rejected with a clear message; OCR is out of scope.
- **Scope.** This is a multi-session effort. Each milestone is reported honestly as tested /
  untested / requires credentials.

## 10. Milestone 4 decision record

| # | Decision | Rationale |
|---|---|---|
| M4-1 | Requirements stored in their own table (`job_requirements`); job info/keywords as JSON on `job_descriptions`. | Requirements are queried and counted individually; the rest is read as a document. No data is stored twice. |
| M4-2 | Required/preferred is decided from the job description's wording where explicit; the model's label is a fallback, and every requirement records its `classification_source`. | The model cannot turn a "nice to have" into a mandatory requirement, or the reverse. |
| M4-3 | A deterministic skill lexicon (aliases + families) runs alongside the model. | Exact vs related matching must not depend on the model; it also catches skills the model missed (classified *preferred* unless the text says required). |
| M4-4 | Semantic similarity is computed **before** scoring and stored with the match (`job_matches.inputs`); the engine is a pure function. | Reports are reproducible from stored data (`reproduce_report`), and the same inputs always give the same score. |
| M4-5 | Embedding cache: short skill terms global; longer texts (bullets, requirement sentences) per user, deleted with the account. | Avoids repeated API calls without sharing personal text across users. |
| M4-6 | "A or B" alternatives are grouped and scored once by the best-evidenced member. Grouping is conservative (direct "A or B" / "A/B" only). | Otherwise a candidate with FastAPI is penalised for lacking Django when the job accepts either. |
| M4-7 | `POST /api/analyze` keeps its contract, but its `score` is now the deterministic match percentage; the LLM fit-score prompt was removed. | The old AI-generated score is replaced, not kept as a parallel number that could disagree. Analyses created earlier keep their original scores (`job_match_id = NULL`). |
| M4-8 | Matches count against the AI quota only when uncached embeddings must be fetched. | Re-running a match costs nothing and should not consume a user's daily limit. |

## 11. Milestone 5 decision record

| # | Decision | Rationale |
|---|---|---|
| M5-1 | The model returns wording by item id only; employers, titles, dates, degrees, institutions and certification names are copied from the original by code. | Fabrication of locked facts becomes impossible by construction rather than merely detected. |
| M5-2 | Each rewritten unit is verified against its **own** evidence (cited source bullets for a bullet, the whole verified resume for the summary). | A real figure moved to the wrong bullet is a misattribution; injected raw text cannot vouch for an organisation. |
| M5-3 | Blocking issues auto-reject a suggestion and it cannot be accepted; warnings wait for the user; manual edits are kept but flagged. | The user is the authority on their history, the AI is not. |
| M5-4 | Every change is an immutable version (`UNIQUE(rewrite_id, number)` + `base_version` → 409 on conflict), pruned to `REWRITE_MAX_VERSIONS`, version 1 kept. | Revisit/restore, safe concurrent tabs, bounded storage. |
| M5-5 | Before/after scores use the existing engines on both versions rendered identically; match scores exclude semantic similarity on both sides. | No AI scores; like-for-like comparison without AI calls on every edit. |
| M5-6 | Exports generated on demand and streamed; only metadata stored. WeasyPrint (shared HTML with preview) + python-docx; WeasyPrint gets a refusing URL fetcher. | No files at rest, preview = PDF, no SSRF. |
| M5-7 | Deleting a job keeps rewrites but unlinks them and scrubs job-derived data; deleting a resume deletes its rewrites. | Keeps the user's work while honouring deletion. |
| M5-8 | Three templates (modern, minimalist, corporate) delivered in Milestone 5; the remaining two planned templates stay in Milestone 6. | Milestone 5 brief asked for at least three. |


## 12. Milestone 6 decision record

| # | Decision | Rationale |
|---|---|---|
| M6-1 | Technical and Graduate templates added; all five share one single-column definition and differ in typography, density and section order. | Keeps every template ATS-readable and both formats consistent. |
| M6-2 | Coursework is an optional, user-entered list per education entry, verified against the original resume text (unsupported courses are blocking user claims). Not extracted by the AI. | The Graduate template needs it; adding it to the AI extraction would change prompts that can only be verified with live calls. |
| M6-3 | Exporting a version with blocking or warning issues needs `acknowledge_unverified: true` (server-enforced, 409 otherwise); the UI lists the claims and requires a checkbox per version. The confirmation and verification status are stored with the export metadata (migration `0006`). | Approved decision: users may export their own edits, with prominent warnings and explicit acknowledgement, without silently removing content. |
| M6-4 | Deleting a job keeps the rewrite and all versions, sets `job_detached_at`, scrubs all job-derived data (including suggestion keywords, requirement ids and rationales, and job wording in issue messages) but keeps issue severities. | Approved decision; a claim must never become "verified" because the job was deleted. |
| M6-5 | Frontend tests use Vitest 4.1.12 + Testing Library with a fake backend at the `fetch` boundary. This required **Vite 5.4 → 6.4.5** (Vitest ≥ 4.1.12 requires Vite ≥ 6; Vitest 3.x carries critical/moderate advisories). No source or config changes were needed, and `npm audit` reports 0 vulnerabilities. | Avoids adding a test runner with known advisories. Reversible (reinstall `vite@^5.4` and `vitest@3.2`, accepting the advisories); flagged for approval. |
| M6-6 | Page footer ("Name — page n of N") on continuation pages only, in both formats. | Multi-page resumes stay identifiable when printed; contact details stay in the body for ATS parsers. |
| M6-7 | Gemini structured-output schema enforcement (`response_json_schema`) is recommended but not implemented. | It changes live model behaviour and must be verified with real calls first ([gemini-verification-plan.md](gemini-verification-plan.md)). |


## 13. Milestone 7 decision record

| # | Decision | Rationale |
|---|---|---|
| M7-1 | Frontend API types are **generated** from the FastAPI OpenAPI schema (`scripts/export_openapi.py` + `openapi-typescript`), checked in, and verified in CI. A `Wire<T>` mapped type marks response fields as present. | No hand-maintained copy of the Pydantic models; backend contracts unchanged. Pydantic fields with defaults are optional in the schema but always serialised. |
| M7-2 | `react-router` **7.18** (declarative `<Routes>`), not 8. | v8 requires React 19; upgrading React is out of scope. |
| M7-3 | TypeScript **5.9**, ESLint **9**, Prettier 3. | typescript-eslint supports TS < 6.1 and openapi-typescript TS 5; jsx-a11y supports ESLint ≤ 9. |
| M7-4 | `npm overrides`: `@typescript-eslint/typescript-estree` → `minimatch@11.0.5`. | Clears GHSA-g3hv-75wg-m249 (moderate, dev-only lint tooling) without downgrading typescript-eslint; `npm audit` reports 0. |
| M7-5 | Resume uploads use `XMLHttpRequest` (`apiUpload`) for progress; everything else uses `fetch`. Error envelope, CSRF and session expiry are handled identically. | `fetch` cannot report upload progress. |
| M7-6 | Duplicate uploads are only *pointed out* by file name. | The API stores a content hash but does not expose it; no backend change was made for this. |
| M7-7 | The original combined review (`POST /api/analyze`) is kept as "Quick reviews" (`/reviews`). | It must not be removed silently; removal of the legacy endpoints stays a separate, explicit decision. |
| M7-8 | Native `<dialog>` replaces `window.confirm` for deletions. | Explains consequences, focuses Cancel, consistent styling; still native focus trapping and Escape. |
| M7-9 | The Playwright journey is in the repository (`frontend/e2e`) and CI (`.github/workflows/frontend.yml`), using the existing fake AI provider. `mock_ai_server.py` gained `--allow-origin` (dev-only) so the run uses its own ports. | Approved M6 workflow, now repeatable. No live AI calls. |
| M7-10 | In the browser test, clicks on the rewrite page wait 300 ms after scrolling, and trace DOM snapshots are disabled. | Diagnosed: Chrome may route a click issued during a long programmatic scroll to the out-of-process sandboxed preview iframe (no events reached the page); the trace recorder's injected script is blocked in that iframe and logged as a console error. Neither affects users. |



## 14. Milestone 8 decision record

| # | Decision | Rationale |
|---|---|---|
| M8-1 | **`BACKEND_ACCESS_KEY`** (new, **approved 2026-11-11**): every request except the liveness probe `/api/v1/health` must carry `X-Backend-Access-Key` (constant-time compare, 403 otherwise; never logged). Render generates it; Vercel stores it server-only and injects it. **Required in production — fail closed** (start-up refuses without it, or with fewer than 32 characters). Disabled locally, in Compose and in tests unless a test exercises it. | Without it the Render URL is publicly callable, and a direct caller can forge `X-Forwarded-For` to dodge per-IP limits. With it, `FORWARDED_ALLOW_IPS='*'` is sound. |
| M8-2 | `vercel.json` uses `routes` (not `rewrites`): `${BACKEND_URL}` via `env`, the key via a `request.headers` transform, then filesystem, missing-asset 404, SPA fallback. | `rewrites` cannot read environment variables or set request headers; the backend URL and key stay out of the repository and the bundle. |
| M8-3 | Migrations are run deliberately: `python -m app.cli migrate` (PostgreSQL advisory lock) from Render's `preDeployCommand` and the Compose `migrate` one-shot service; `RUN_MIGRATIONS_ON_START` for hosts without a pre-deploy step. `Database.migrate()` (dev auto-migrate) uses the same lock. | Never concurrent, never from web workers; a failed migration stops the deploy. |
| M8-4 | The Compose stack runs the production image with `APP_ENV=development`. | Production mode requires HTTPS origins and `Secure` cookies, impossible on `http://localhost` without weakening the checks (not done). Real production mode is verified separately with `docker run` (CI job `images`). |
| M8-5 | Development is an override file (`compose.dev.yaml`), not a profile; the fake-AI test stack is another override (`compose.fake-ai.yaml`) run under its own project name and port. | `docker compose up --build` stays production-like; test data can never mix with the local stack's volume. |
| M8-6 | Fake AI in containers: a `fake-ai` image target (production image + tests + dev tools); `mock_ai_server.py` gained `--host`, `--database-url`, and pins one worker. | Exercises the real containers, nginx and PostgreSQL with no credentials; never referenced by `render.yaml`. |
| M8-7 | API responses default to `Cache-Control: no-store` (explicit values kept). | Vercel now caches external rewrites according to upstream headers; per-user JSON must never be cached. |
| M8-8 | **Bug fix:** `app/ai/gemini.py` imported `httpx`, which is not a runtime dependency; google-genai 3.0 uses `httpx2` by default. The production image crashed at start-up with a Gemini key, and real SDK timeouts were not classified as timeouts/retryable. It now recognises both libraries' errors; `httpx2` is pinned in `requirements.txt`. | Found by the production-mode container check; dev environments masked it because they install `httpx`. Regression tests added. |
| M8-9 | CJK fonts (`fonts-noto-cjk`) stay opt-in (`INSTALL_CJK_FONTS=false` by default; **approved 2026-11-11**). | +169 MB (+31%) for a language set the app does not declare (English scoring lexicon). Without the fonts, PDFs do **not** visually support CJK (empty boxes); the correct text layer does not change that. Enabling later is one build argument. |
| M8-13 | `Rewrite.test.jsx › requires a resume, then sends …` timeout 5 s → 10 s; assertions unchanged (**approved 2026-11-11**). | It timed out once at 5.56 s on a busy machine; CI runners can be slower. |
| M8-10 | Pinned bases: `python:3.12.16-slim-bookworm` (same Debian release as the Milestone 6 PDF QA), `node:24.22.2-alpine`, `nginxinc/nginx-unprivileged:1.28.2-alpine`, `postgres:16.15-alpine`. Tags, not digests. | Exact, reproducible versions; digest pinning would also freeze security patches. |
| M8-11 | No Render cron job and no Render static site. | No retention purge command exists in the application; the frontend is on Vercel. |
| M8-12 | Python JSON logs drop uvicorn's ANSI `color_message` duplicate. | It leaked escape codes into structured logs. |


## 15. Milestone 9 decision record

| # | Decision | Rationale |
|---|---|---|
| M9-1 | `tests/integration/test_deployment.py` dictionaries annotated `dict[str, Any]`; `backend.yml` runs `mypy app tests scripts`. | The README promised type-checked tests, but CI checked only `app` and `scripts`, so 36 test-typing errors went unnoticed. Typing only; no assertion changed. |
| M9-2 | Production mode verified behind a local TLS proxy that injects the key (standing in for Vercel), on internal-only networks. | Closes most of the M8-4 gap without relaxing HTTPS/origin validation and without any route to Gemini. Real Vercel behaviour stays a first-deployment check. |
| M9-3 | The WeasyPrint `url_fetcher` incompatibility (final audit N1) was first documented, then **fixed after approval**: a refusing `weasyprint.URLFetcher` subclass (`fail_on_errors=False`, no allowed protocols) plus 11 regression/end-to-end tests. | Same deny-all policy; a refused resource is now skipped instead of crashing rendering. Narrow change at a security boundary, approved 2026-11-11. |
| M9-5 | CJK fonts stay opt-in (`INSTALL_CJK_FONTS=false`), re-confirmed. | +169 MB is not justified for the declared (English) language support; the option stays documented. |
| M9-4 | Milestone 9 marked complete, and the application assessed as **ready for a controlled private first deployment, not for real users**. | All local exit criteria pass; the P0 items need credentials, hosting or a push, which were out of scope. |

