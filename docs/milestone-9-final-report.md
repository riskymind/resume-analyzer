# Milestone 9 — Final Verification Report and Handover

_Date: 2026-11-11 · HEAD `ac8d085` on `main`, all Milestone 1–9 work uncommitted · audience: the project owner
deciding on a first deployment, and the developers who will carry it out. Nothing was deployed, staged,
committed or pushed. No live Gemini call was made. No production database or credential was used._

## 1. Executive summary

**Every Milestone 9 exit criterion that can be checked locally passes.** That covers the backend on SQLite and
PostgreSQL 16, lint, formatting, strict types, the frontend checks, the Playwright journey (twice), the image
builds, both Compose stacks, the production access key on the real production image, PDF and DOCX in all five
templates inside the container, migrations, secret scans and the CI configuration. Test counts are identical
to the Milestone 8 baseline (§4). Two documentation and typing defects were fixed. One latent PDF-renderer
defect was found (N1). After your approval it was fixed in a follow-up the same day, with 11 new tests
(§21).

**Readiness assessment: ready for a controlled, private first deployment. Not ready for real users.**
"Controlled" means a preview/staging deployment used by the owner and testers with fictional data, whose
purpose is to complete the external verification that cannot be done locally. Three P0 items stand between
that and real users (§17):

1. The code is not in version control. All of Milestones 1–9 is uncommitted, so Render and Vercel have
   nothing to build and GitHub Actions has never run.
2. The real Vercel and Render behaviour has never been observed (routing, header injection, pre-deploy
   migration, time limits).
3. Live Gemini behaviour for the core AI features is unverified. Only resume extraction passed with the
   final schema, job extraction failed once, and the rewrite has never run against the real model.

## 2. Final architecture

```
Browser ── HTTPS ──► Vercel: static SPA (frontend/dist, React 18 + TS)
                      route /api/(.*) → ${BACKEND_URL}/api/$1 + x-backend-access-key (server-side only)
                                  ▼
                     Render web service (Docker, backend/Dockerfile, uid 10001, $PORT)
                      FastAPI · access-key middleware (only /api/v1/health exempt) · sessions + CSRF
                      services: parsing → AI extraction (verified) → deterministic scoring / matching
                                rewrite generation → code verification → versions → PDF/DOCX on demand
                      preDeployCommand: python -m app.cli migrate (advisory lock)
                         │                                   │
                         ▼                                   ▼
                     Render PostgreSQL 16 (15 tables,     Gemini (google-genai 3.0.0,
                     Alembic head 0006, private network)   gemini-3.6-flash, gemini-embedding-001)
```

Locally the same images run under Docker Compose with nginx in Vercel's place. Details:
[deployment-architecture.md](deployment-architecture.md) and [milestone-9-final-audit.md §2](milestone-9-final-audit.md#2-architecture-as-built).

## 3. Features implemented (Milestones 1–8)

| M | Delivered |
|---|---|
| 1 | Audit and plan ([architecture-audit.md](architecture-audit.md), [refactoring-plan.md](refactoring-plan.md)) |
| 2 / 2b | `app/` layered backend, typed settings, JSON logs with redaction, error envelope, upload validation, SQLAlchemy + Alembic with legacy-data migration, accounts (Argon2id, server-side sessions, CSRF), per-user isolation, rate limits, account deletion |
| 3 | PDF/DOCX/Markdown parsing (malformed, empty, encrypted, unsupported handled), verified structured extraction, deterministic quality and ATS scoring |
| 4 | Job description extraction, skill lexicon, cached embeddings with disclosed fallback, deterministic match engine with gap analysis |
| 5 | Rewriter: four modes, scopes, locked facts copied by code, per-unit verification, accept/reject/edit, immutable versions and restore, before/after scores |
| 6 | Five templates, WeasyPrint PDF, python-docx DOCX, preview, export acknowledgement for unverified claims, job detachment, Gemini structured output (R1–R4) |
| 7 | TypeScript frontend, router, dashboard, upload with progress, analysis, matching, rewrite editor, preview/download, accessibility work, Vitest and Playwright |
| 8 | Docker images, Compose stacks, `render.yaml`, `vercel.json`, CI workflows, backend access key (fail closed), `httpx2` fix |

## 4. Backend verification results

Environment: macOS 15 (Intel), Python 3.13.6 (venv), Homebrew Pango (PDF tests ran, not skipped).

| Check | Result | Milestone 8 baseline |
|---|---|---|
| `ruff check .` (0.17.4) | ✅ clean | clean |
| `ruff format --check .` | ✅ 136 files formatted | clean |
| `mypy app scripts` (2.4.1, strict) — CI command until now | ✅ 95 files clean | clean |
| `mypy app tests scripts` — README command | ❌ 36 errors in `tests/integration/test_deployment.py` → **fixed** (typing only) → ✅ 135 files clean | not run |
| Root `scripts/` ruff + strict mypy | ✅ | ✅ |
| `pip-audit -r requirements.txt --strict` | ✅ no known vulnerabilities | ✅ |
| **pytest, SQLite** | ✅ **809 passed, 1 skipped** (288 s). The skip is the PostgreSQL-only advisory-lock test | 809 / 1 |
| **pytest, PostgreSQL 16.15** (throwaway container, `TEST_DATABASE_URL`) | ✅ **810 passed, 0 skipped** (624 s) | 810 |
| Export suites inside the Linux container (fake-AI image, real Pango/fonts) | ✅ 123 passed, 0 skipped | 84 export tests in M6 (suite has grown) |

**Why the counts are unchanged:** Milestone 9 added no application code and no tests; the only test-file
change is a type annotation. Equal counts on unchanged code mean no regression and no lost tests. A higher
count would only have meant new tests.

**Application areas (all covered by the suites above; collected test counts per file in brackets):**

| # | Area | Evidence |
|---|---|---|
| 1–2 | Registration, login, sessions (creation, rotation, idle and absolute expiry, logout) | `test_auth.py` [39], `test_security.py` [26]; 7 session lifecycle tests |
| 3 | CSRF | 22 tests (origin + session-bound token); re-checked live in production mode (§9) |
| 4 | Per-user isolation | `test_isolation.py` [11]; smoke test cross-account 404 |
| 5 | Account deletion and cleanup | `test_account_deletion.py` [12]; smoke test and Playwright |
| 6 | Parsing and structured extraction | `test_document_parsing.py` [36], `test_extraction.py` [22], `test_resumes_api.py` [26] |
| 7 | Deterministic quality scoring | `test_scoring.py` [38], `test_sections_and_signals.py` [55] |
| 8 | Job description parsing | `test_job_extraction.py` [23] |
| 9 | Deterministic matching | `test_matching_engine.py` [37], `test_job_matching_api.py` [36] |
| 10 | Embedding cache and disclosed fallback | `test_semantic.py` [10]; 19 tests matching embedding/semantic/fallback |
| 11–12 | Rewriting, verification, protected facts | `test_rewrite_generator.py` [20], `test_rewrite_verification.py` [39], `test_rewrites_api.py` [53] |
| 13 | Versioning and restore | 10 tests; Playwright "view and restore version 1" |
| 14–15 | PDF and DOCX, five templates | `test_export_quality.py` [56], `test_rewrite_exports.py` [28]; smoke 5 × 2 exports |
| 16 | Unverified user claims and export acknowledgement | 3 acknowledgement tests; Playwright download gating |
| 17 | Job deletion and rewrite detachment | 2 tests; Playwright detachment |
| 18 | Rate limiting | `test_rate_limits.py` [13], 34 tests overall; re-checked through proxies (§9, §7) |
| 19 | Upload validation and size limits | `test_file_validation.py` [28]; 28 size/signature/MIME tests |
| 20 | Error handling, privacy-safe logging | `test_platform.py` [23], log tests; container log scans (§7, §9) |

## 5. Frontend verification results

| Check | Result | Baseline |
|---|---|---|
| `npm ci` | ✅ 451 packages | — |
| `npm audit` | ✅ 0 vulnerabilities | 0 |
| `npm run check`: `tsc` (app + node configs), ESLint 9 (incl. jsx-a11y), Prettier, Vitest, build | ✅ **11 files, 97/97 tests**; JS 292.69 kB (88.96 kB gzip), CSS 27.24 kB | 97/97 |
| OpenAPI schema and generated types vs backend | ✅ no drift (regenerated and compared) | — |
| Bundle scan | ✅ no `BACKEND_ACCESS_KEY`, `x-backend-access-key`, `GEMINI`, `onrender.com`, `DATABASE_URL`, `localhost:8000`, `AIza`. The only absolute URLs are XML namespaces, library doc links and react-router's `http://localhost` URL-parsing base | ✅ |

The Vitest run happened while the PostgreSQL suite was loading the machine. The `Rewrite.test.jsx` test that
flaked once at 5.56 s in Milestone 8 (now 10 s, M8-13) passed. Areas covered by Vitest: protected routes and
redirect-back, expired-session sign-out and return, unknown-route 404, retry when the server is unreachable,
dashboard empty/loading/per-panel error and retry, upload validation, drag-and-drop, progress, cancel and
duplicate notice, analysis, match pages, rewrite editor (23 tests), diff, document pickers, and `vercel.json`
route emulation.

## 6. Playwright results

| Run | Result |
|---|---|
| Default mode: own Vite + fake-AI server on SQLite, local Chrome (`E2E_PYTHON=../backend/venv/bin/python`) | ✅ **16/16** (30.1 s) |
| Against the containerised fake-AI stack (`E2E_BASE_URL=http://localhost:8090`: nginx → API → PostgreSQL) | ✅ **16/16** (28.3 s) |

The journey covers the skip link and sign-in redirect, register/sign-out/sign-in, upload, match, rewrite,
accept/reject (blocked suggestions cannot be accepted), the unverified-edit acknowledgement gating PDF and DOCX
downloads, all template previews, version restore, **deep links surviving a reload**, the dashboard, job
deletion detaching a rewrite (Escape cancels the dialog), 390/768 px layouts without horizontal scroll, the
404 page, account deletion, and "no JS errors, no 5xx, only the expected 4xx".

Note: the default mode needs `python` on `PATH` or `E2E_PYTHON`; the first attempt here failed for that reason
alone (now documented in the README).

## 7. Docker and Compose results

| Check | Result |
|---|---|
| `docker build backend` (production target) | ✅ 542 MB. Fully cached, so the current source is identical to the inputs of the cached layers |
| `docker build --target fake-ai backend` | ✅ 716 MB (rebuilt: test file changed) |
| `docker build frontend` (runtime) | ✅ 81.9 MB |
| `docker compose config` (base, `+dev`, `+fake-ai`) | ✅; empty `POSTGRES_PASSWORD` refused; host ports only on 127.0.0.1 (base: web 8080; dev: 5173, 8000, 5433) |
| **Production-like stack** (`compose.yaml`, isolated env file, no AI key) from clean volumes | ✅ up in 22 s: `db` healthy → `migrate` exit 0 → `api` healthy → `web` healthy; `/healthz` ok; `/api/v1/health` ok; `/api/v1/health/ready` `degraded` (`ai_provider: not_configured`, expected); smoke `--no-ai` **20/20**; account survived `down` + `up` (migrate: "Already up to date at revision 0006"); API uid 10001; logs: 0 errors, 0 password/e-mail/DB-password occurrences |
| **Fake-AI stack** (`+ compose.fake-ai.yaml`, own project) from clean volumes | ✅ up in 67 s incl. build (one transient Docker Hub TLS timeout on the first attempt, then succeeded); migrate empty → 0006 |
| Frontend → backend via nginx, resume upload + analysis, job, match, rewrite (fake AI), **5 templates × PDF and DOCX**, deep links, CSRF/session refusals, cross-account 404, deletion | ✅ smoke test **38/38** |
| Playwright against the containers | ✅ 16/16 (§6) |
| Export quality suites inside the container | ✅ 123 passed (font embedding, pagination "page n of N", wrapping of 140-char tokens and long URLs, DOCX structure, all templates) |
| Spoofed `X-Forwarded-For` through nginx | ✅ per-IP login limit still reached (nginx overwrites the header) |
| Container logs (509 lines) | ✅ 0 tracebacks/ERROR/`[emerg]`; 0 occurrences of the DB password, CSRF or session tokens, test passwords, e-mail addresses, the sample resume's name, three resume bullets, or job-description text |
| Non-root | ✅ API uid 10001 (image and running container), web uid 101 |

## 8. PostgreSQL and migrations

On a throwaway `postgres:16.15-alpine`, and repeated on SQLite:

| Check | PostgreSQL 16.15 | SQLite |
|---|---|---|
| Empty → head with `python -m app.cli migrate` | ✅ `(empty database) -> 0006`, 15 tables | ✅ |
| Idempotent re-run | ✅ "Already up to date at revision 0006" | — |
| `alembic check` (models vs migrations) | ✅ no new operations | ✅ |
| `downgrade base` → `upgrade head` | ✅ (only `alembic_version` left at base) | ✅ |
| Step-wise: six single downgrades, six single upgrades, then `alembic check` | ✅ | — |
| Concurrent runners (advisory lock) | ✅ the PostgreSQL-only test in the 810 | n/a |
| Migrate step in both Compose stacks and the production topology | ✅ | — |

## 9. Production access-key verification

All checks used the **actual production image** (`resume-analyzer-api:local`, default target) with throwaway
values, on Docker networks marked `internal` (no route to the internet; an outbound HTTPS request from the
API container failed with `URLError`), so no AI endpoint could be reached.

**Start-up (18/18 passed):**

| Check | Result |
|---|---|
| `APP_ENV=production` (image default) with no configuration | ✅ exit 1, `Configuration error:` lists `BACKEND_ACCESS_KEY must be set in production`, no traceback |
| Key unset / blank / whitespace only | ✅ exit 1, same message |
| Key of 31 characters | ✅ exit 1, "must be at least 32 characters"; message does not echo the value; `check-config` also refuses |
| Key of exactly 32 characters | ✅ accepted |
| `check-config` output | ✅ never prints the key; DB password masked |
| Image contents | ✅ no tests, `scripts/`, `.env` or database files; no pytest, ruff or httpx; code read-only for the app user; WeasyPrint and `httpx2` import; no secret-named variable in the image environment or layer history |

**Requests (31/31 probes, raw paths without client-side normalisation, sent inside the API container):**

| Check | Result |
|---|---|
| `/api/v1/health` without key | ✅ 200 (the only exemption; query strings allowed) |
| `/api/health` (legacy alias) without key | ✅ **403** |
| `/api/v1/health/` (trailing slash), `/API/V1/HEALTH`, `//api/v1/health`, `/api/v1/health/../health/ready`, `/api/v1/health%2Fready` | ✅ all 403 |
| Readiness without key / wrong key of the same length / truncated / with suffix / empty header / key in `Authorization` | ✅ all 403 |
| Readiness with the valid key (any header-name case) | ✅ 200 |
| Two key headers, wrong one first | ✅ 403 (the first header is used) |
| `/api/docs`, `/api/openapi.json`, `/api/redoc` | ✅ 403 without key, 404 with key (disabled in production) |
| Unknown paths, `/`, `/api/v1/auth/me`, login POST, OPTIONS without key | ✅ 403 |
| Forged `X-Forwarded-For` without key | ✅ 403, so it cannot reach the rate limiter |
| 403 body | ✅ standard JSON envelope with `request_id`, no internals, `Cache-Control: no-store`; the key never appears in any response |
| Constant-time comparison | ✅ `hmac.compare_digest` in `BackendAccessKeyMiddleware` (code review; unit-tested in M8) |

**Full production-mode topology** (closing the Milestone 8 gap, M8-4):
`HTTPS edge (nginx, self-signed TLS, overwrites X-Forwarded-For, injects the key) → web image → API
(APP_ENV=production, CORS_ORIGINS=https://localhost:8443, 2 workers) → PostgreSQL 16`. The edge stands in for
the Vercel router; HTTPS and origin validation were **not** weakened.

| Check | Result |
|---|---|
| Migration, then API and web healthy | ✅ |
| `/api/v1/health/ready` through the edge | ✅ `ok` (database ok, AI configured with a placeholder; never called) |
| Same request through the web nginx **without** the edge (no key) | ✅ 403 |
| Smoke test over HTTPS (`--no-ai`): deep links, JSON 404s, asset 404, security headers, `no-store`, register, cookie, session, CSRF refusals, account deletion | ✅ **20/20** |
| Session cookie | ✅ `__Host-ra_session=…; HttpOnly; Max-Age=604800; Path=/; SameSite=lax; Secure` |
| Login with `Origin: https://evil.example` | ✅ 403 |
| Login without `Origin`/`Referer` | 200, **by design** (`app/core/security.py:97`: non-browser clients cannot carry a victim's cookie; the CSRF token is still required once authenticated) |
| CORS preflight | ✅ no `Access-Control-Allow-Origin` for an untrusted origin; exact origin + credentials for the trusted one |
| Logout without CSRF token | ✅ 403 |
| Registration with a different spoofed `X-Forwarded-For` each time | ✅ 429 once the 5/hour per-IP limit was reached |
| Logs (API, web, edge, DB) | ✅ 0 occurrences of the key, DB password, passwords, e-mail addresses, session/CSRF tokens; 0 tracebacks/errors. Logs contain user and session **row UUIDs** only (the cookie is a separate random token stored hashed) |
| Graceful shutdown (`docker stop`) | ✅ exit 0 after 1 s, lifespan shutdown logged for both workers |

**What this does not prove:** that Vercel's router expands `${BACKEND_URL}`, applies the header transform,
overwrites `X-Forwarded-For`, passes cookies through and allows 12 MB bodies and > 90 s requests. These are
first-deployment checks (§18).

**Vercel / Render configuration (static):** `vercel.json` sets `x-backend-access-key` with `op: set` from
`$BACKEND_ACCESS_KEY` (server-side `env`, overwrites any client value); `render.yaml` uses
`generateValue: true`. Neither file contains a secret.

## 10. PDF/DOCX export verification

| Requirement | Automated coverage | Status |
|---|---|---|
| All five templates, PDF and DOCX | `test_export_quality.py`, `test_rewrite_exports.py`, smoke test (5 × 2 through nginx), Playwright previews | ✅ |
| Long resumes, page numbering | Long sample runs to 3+ pages; footer "page n of N" on pages 2+ only (PDF); `PAGE`/`NUMPAGES` fields, different first page (DOCX) | ✅ |
| URL and long-token wrapping | 140-character token and long URL wrap within margins (PDF) | ✅ |
| Headings and lists | Keep-with-next, `List Bullet` numbering, no typed glyphs (DOCX); headings stay with entries | ✅ |
| Protected facts | Locked facts copied by code; verification tests | ✅ |
| Export acknowledgement | Server returns 409 without `acknowledge_unverified`; acknowledgement tied to the exported version | ✅ |
| Safe filenames | ASCII slug in `Content-Disposition: attachment` | ✅ |
| PDF external-resource blocking | `TestPdfResourceFetcher` (§21): fetcher interface, every scheme refused without opening, hostile HTML end-to-end through `render_pdf` with a listening socket and a secret-marker file, all five templates never consult the fetcher | ✅ |
| Inside the Linux image | 123 export tests in the container | ✅ |

**Defect N1, fixed after approval (§21):** WeasyPrint 70 expects its `url_fetcher` to be a `URLFetcher` object.
When the former plain-function fetcher refused a URL, WeasyPrint read `url_fetcher._fail_on_errors` and
crashed with `AttributeError`. No request was ever made, and the template contains nothing fetchable, so real
exports were unaffected. The renderer now passes a refusing `URLFetcher` subclass; refused resources are
skipped.

**Manual checks that remain:** automated structural checks do **not** replace opening the DOCX files in
Microsoft Word or another word processor. **Word inspection has not happened**; the checklist is in
[export-qa.md §4](export-qa.md#4-docx-what-is-and-is-not-verified).

**CJK:** `INSTALL_CJK_FONTS=false` is the default (re-confirmed by the owner on 2026-11-11; kept documented for a future decision). The fonts add about 169 MB (542 → 712 MB). Without them, CJK
characters render as empty boxes in PDFs (the text layer is correct, but that does not fix what users see).
The font-enabled image was tested in Milestone 8 (Noto Sans CJK JP embedded, rendered correctly). It was
**not rebuilt or re-tested in Milestone 9**, and the default deployment has **no** CJK visual support.

## 11. Security review

| Control | Status | Evidence |
|---|---|---|
| Production fails closed without a valid access key | ✅ Pass | §9 |
| Only `/api/v1/health` unauthenticated; `/api/health`, readiness, docs, unknown paths not exempt | ✅ Pass | §9 |
| Constant-time key comparison; key never logged, returned or bundled | ✅ Pass | §9, §5 |
| Vercel sends the key server-side; Render generates it | ✅ Pass (config) / **Not verified** on the platforms | §9 |
| Session cookie attributes in production | ✅ Pass | §9 |
| CSRF (origin + token) | ✅ Pass | §4, §9 |
| CORS not overly permissive | ✅ Pass (exact origins; `*` and `http://` refused in production) | §9, config |
| Ownership checks / cross-user access | ✅ Pass | `test_isolation.py`, smoke test |
| Rate limits not bypassable with forged forwarded headers | ✅ Pass through nginx and the local edge; **Not verified** behind Vercel | §7, §9 |
| Upload validation (signature, MIME, size, encryption) | ✅ Pass | 28 tests; smoke test |
| PDF rendering cannot make external requests or read local files | ✅ Pass (N1 fixed; refused resources are skipped) | §10, §21 |
| No sensitive data in logs | ✅ Pass | §7, §9 |
| No stack traces or secrets in production error responses | ✅ Pass (403/404 checked live; 500s use the error envelope, `test_platform.py`) | §9 |
| Prompt injection | ✅ Pass with the fake provider (fencing + code verification); **Not verified** against the real model (G9/G10 never run) | [gemini plan §4](gemini-verification-plan.md#4-status-at-milestone-9-2026-11-11-no-live-calls-made) |
| Secrets in the repository, manifests, images or bundle | ✅ Pass | §5, §9, [audit §1](milestone-9-final-audit.md#1-repository-state) |
| Least privilege in containers | ✅ Pass (non-root, read-only code, internal DB network, ports on 127.0.0.1) | §7 |

## 12. Dependency audit

| Ecosystem | Result |
|---|---|
| Python runtime (`pip-audit -r requirements.txt --strict`) | ✅ no known vulnerabilities |
| npm (`npm audit`, all dependencies) | ✅ 0 vulnerabilities |
| Base images | Pinned tags (`python:3.12.16-slim-bookworm`, `node:24.22.2-alpine`, `nginxinc/nginx-unprivileged:1.28.2-alpine`, `postgres:16.15-alpine`). **No image vulnerability scan** (Trivy/Grype) was run |
| Ongoing monitoring | No Dependabot/Renovate configuration (issue P2-3) |

## 13. Gemini verification status

No live calls were made in this milestone. Full breakdown:
[gemini-verification-plan.md §4](gemini-verification-plan.md#4-status-at-milestone-9-2026-11-11-no-live-calls-made).

| Category | Scenarios |
|---|---|
| Verified live, final schema | G1 |
| Passed live, superseded schema only | G2, G4 |
| Failed live | G3 (superseded schema); G1–G3 with the first schema (400) |
| Schema-independent live pass | G13 |
| Never attempted | G5–G12, G14 (rewrite, per-section regeneration, modes, prompt injection, size, timeout, consistency) |
| Failure causes | 400 and sparse output: schema configuration (since fixed); 503: provider overload (14 of 26 keyed requests); 429: quota (4) |
| Timeout/retry | Verified offline (mocked, fake clock, `httpx2` and `httpx` errors); real timeout not observed |
| Model/SDK | Model names answered live on 2026-11-09. **The current adapter, after the `httpx2` change, has only been exercised synthetically** |

**Recommendation:** a separately authorised session of about 20–25 calls, with a dedicated low-quota (ideally
paid-tier) key, fictional fixtures and a local SQLite database, running G1 and G3 first, then G5, G6, G9 and
G10. Stop on the first 429. A failure in G3, G5, G6, G9 or G10 blocks AI features for real users.

## 14. Render / Vercel verification status

| Platform | Verified | Not verified |
|---|---|---|
| Render | `render.yaml` against Render's published JSON schema (re-run today); image behaviour under production settings (§9); `$PORT` binding; the migrate command; health path | Blueprint apply; `preDeployCommand` in Render's Docker runtime; generated key; health check by Render; `maxShutdownDelaySeconds`; Render CLI validation (not installed) |
| Vercel | `vercel.json` against Vercel's schema (re-run today); route-order emulation test; the same contract in nginx; a key-injecting TLS proxy standing in for Vercel (§9) | `env` expansion in `routes`; the `request.headers` transform; `X-Forwarded-For` overwrite; cookie pass-through; 12 MB bodies; > 90 s requests; SPA fallback on Vercel's CDN |

## 15. GitHub Actions verification status

| Check | Result |
|---|---|
| `actionlint` 1.7.8 with shellcheck 0.11.0 on all three workflows | ✅ 0 errors |
| Backend tests (SQLite, PostgreSQL 16 service, migration round trip) represented | ✅ `backend.yml` (now also `mypy app tests scripts`) |
| Frontend checks, `npm audit`, Playwright, OpenAPI drift represented | ✅ `frontend.yml` |
| Docker builds, production access-key checks, fake-AI stack, smoke test, Playwright, log scan | ✅ `docker.yml` |
| Locally executable pieces | ✅ every command was run locally (§4–§9); manifest schema validation and the secret grep were run with CI's pinned `jsonschema==4.26.0`/`pyyaml==6.0.3` |
| No live Gemini credential; no deploy or publish step; secrets not printed | ✅ (CI database passwords are throwaway or generated per run; `docker logs` of the production-mode check prints no key) |
| **A successful GitHub-hosted run** | ❌ **None exists.** Nothing has been pushed. Local validation of the configuration is not a hosted run (runner images, service containers, caches and the preinstalled Chrome are only exercised on GitHub) |

## 16. Manual checks outstanding

1. Open the DOCX samples in Microsoft Word (or LibreOffice/Pages) and follow [export-qa.md §4](export-qa.md#4-docx-what-is-and-is-not-verified).
2. A human accessibility pass: screen reader (VoiceOver/NVDA) through the full journey, keyboard-only use,
   zoom to 200 %, a real phone. Automated coverage is lint rules, focus tests and layout widths only.
3. A visual browser review of the deployed site (Safari and Firefox in addition to Chrome; Playwright used Chrome only).
4. Post-deployment checks in [deploy-render.md §4](deploy-render.md#4-verify-after-deploying) and [deploy-vercel.md §4](deploy-vercel.md#4-verify-after-deploying).
5. The live Gemini session (§13).
6. Optional: rebuild with `INSTALL_CJK_FONTS=true` and inspect a CJK PDF if such resumes are expected.

## 17. Prioritised production-readiness issues

P0 = must be resolved before **real users** use any deployment (a private verification deployment may
proceed). P1 = before general availability. P2 = may follow the first deployment. P3 = optional.

| ID | Priority | Issue | Evidence | Action |
|---|---|---|---|---|
| P0-1 | **P0** | All Milestone 1–9 work is uncommitted; Render and Vercel build from GitHub; CI has never run | `git status`: 27 modified, 84 untracked | Commit on a feature branch, push, open a PR, get all three workflows green (your authorization) |
| P0-2 | **P0** | Real Vercel and Render behaviour never observed | §14 | Private first deployment, then the post-deploy checks; fix whatever differs |
| P0-3 | **P0** | Live Gemini unverified for job extraction (G3 failed), rewrite (G5–G8), prompt injection (G9–G10), size and timeout (G11–G12); current adapter never live | §13 | Authorised live session (§13) |
| P1-1 | P1 | Gemini availability: 14/26 live requests returned 503; 429 back-off (1–3 s) cannot outlast per-minute quotas | gemini plan §3 | Paid tier / quota increase; honour `RetryInfo`; user-facing retry message |
| P1-2 | P1 | Database backups and a **tested restore** | Plan-dependent on Render; nothing configured or rehearsed | Enable backups on the DB plan; rehearse a restore into a scratch database |
| P1-3 | P1 | Monitoring and alerting | Only platform log streams; no error tracking, uptime checks or alerts | At least: an uptime check on `/api/v1/health`, Render failure notifications, alerts on 5xx rate |
| P1-4 | P1 | Per-IP rate limits depend on Vercel overwriting `X-Forwarded-For` | Documented by Vercel; verified only with nginx and the local edge | Check `request` log IPs on Render after deploying (deploy-render §4) |
| P1-5 | P1 | No password reset or e-mail delivery | No reset code or e-mail sender exists (decision D1) | Document the support process for locked-out users, or implement reset with an e-mail provider |
| P1-6 | P1 | No automatic data-retention purge | Only expired sessions and rate-limit counters are purged; brief Phase 9 asks for a retention policy | Decide a retention period; implement a purge command and a Render cron job, or state in the privacy notice that data is kept until the user deletes it |
| P1-7 | P1 | DOCX not opened in Microsoft Word | §10 | Manual checklist |
| P1-8 | P1 | No human accessibility or cross-browser review | §16 | Manual pass |
| ~~P2-1~~ | — | WeasyPrint `url_fetcher` incompatibility (N1) | §21 | **Resolved** 2026-11-11 |
| P2-2 | P2 | In-flight request during SIGTERM not exercised; arm64 images not built | M8 report §13 | Redeploy during a rewrite; build arm64 if needed |
| P2-3 | P2 | No Dependabot/Renovate; actions pinned by tag; no image vulnerability scan | Audit N2, N3; §12 | Add `dependabot.yml`; optionally Trivy in `docker.yml` |
| P2-4 | P2 | Gemini cost: thinking tokens dominate (1.3–2.2k per extraction) | gemini plan §3 finding 3 | Thinking budget after G1–G3 pass |
| P2-5 | P2 | Render free plans unsuitable (sleep, expiring DB, no pre-deploy) | deploy-render §3 | Keep `starter` / `basic-256mb` or higher |
| P3-1 | P3 | CJK fonts opt-in (approved M8-9) | §10 | Enable if CJK resumes are expected |
| P3-2 | P3 | Invalid Gemini key surfaces as a generic 502 | gemini plan §3 finding 4 | Map to 503 "AI service is misconfigured" |
| P3-3 | P3 | Python 3.11 declared but untested | Audit §3 | Test or raise `requires-python` to 3.12 |
| P3-4 | P3 | Fake-AI override passes the root `.env` key to `migrate` (unused) | Audit N4 | Blank it in `compose.fake-ai.yaml` |
| P3-5 | P3 | Legacy `/api/analyze` and `/api/analyses` kept (M7-7) | — | Remove in a separate, explicit change |

No unresolved security advisories exist (§12).

## 18. First-deployment checklist

Do **not** treat this as executed; each step needs your authorization.

1. **Version control (P0-1).** Commit Milestones 1–9 on a feature branch, push, open a PR. Confirm `backend.yml`,
   `frontend.yml` and `docker.yml` pass on GitHub. Merge.
2. ~~Decide on N1 and CJK fonts~~: N1 fixed (§21); CJK stays opt-in (owner decision, 2026-11-11).
3. **Render.** New → Blueprint from `render.yaml`; review plan/region (`starter`, `basic-256mb`, `oregon`; the
   DB region cannot change later). Enter `GEMINI_API_KEY` (a dedicated key) and `CORS_ORIGINS` (placeholder
   HTTPS origin until step 5). Apply. Confirm the pre-deploy migration ran and the logs show
   `Configuration OK (APP_ENV=production)` and `backend access key: required`.
4. **Render checks** ([deploy-render.md §4](deploy-render.md#4-verify-after-deploying)): `/api/v1/health` 200;
   `/api/v1/health/ready` 403 without the key and `ok` with it; `/api/health` 403.
5. **Vercel.** Root `frontend`; set `BACKEND_URL` (Render origin, no trailing slash) and `BACKEND_ACCESS_KEY`
   (copied from Render, *Sensitive*), Production and Preview. Deploy a **preview**. Put its exact HTTPS origin
   in Render's `CORS_ORIGINS` and redeploy Render.
6. **Vercel checks** ([deploy-vercel.md §4](deploy-vercel.md#4-verify-after-deploying)): the curl checks; then
   `python3 -I scripts/smoke_test_stack.py https://<preview> --no-ai` (no AI calls); browser: register, upload
   a PDF (4–5 MB), reload a deep link, download PDF and DOCX; DevTools shows only same-origin requests, the
   `__Host-ra_session` cookie, and no `x-backend-access-key`.
7. **Proxy behaviour (P1-4):** confirm Render's request logs show varying client IPs, not Vercel's.
8. **Long requests:** run one rewrite and confirm it completes, or lower `AI_TOTAL_TIMEOUT_SECONDS`.
9. **Live Gemini session (P0-3)** against this private deployment or locally, as in §13.
10. **Before real users:** backups enabled and a restore rehearsed (P1-2), uptime check and alerts (P1-3), a
    decision on retention and password reset (P1-5, P1-6), Word and accessibility passes (P1-7, P1-8). Then set
    the production domain in `CORS_ORIGINS`, and consider `autoDeployTrigger: checksPass`.

## 19. Exact commands

```bash
# Backend (from backend/)
python3 -m venv venv && source venv/bin/activate && pip install -r requirements-dev.txt
ruff check . && ruff format --check . && mypy app tests scripts
pytest -q                                                    # SQLite
docker run -d --rm --name ra-pg -e POSTGRES_USER=t -e POSTGRES_PASSWORD=t -e POSTGRES_DB=t \
  -p 127.0.0.1:55432:5432 postgres:16.15-alpine
TEST_DATABASE_URL=postgresql://t:t@127.0.0.1:55432/t pytest -q   # PostgreSQL 16
DATABASE_URL=postgresql://t:t@127.0.0.1:55432/t python -m app.cli migrate && \
  DATABASE_URL=postgresql://t:t@127.0.0.1:55432/t alembic check
pip-audit -r requirements.txt --strict

# Frontend (from frontend/)
npm ci && npm run check && npm audit
E2E_PYTHON=../backend/venv/bin/python CI=true npx playwright test

# Containers (from the repository root). Use a separate env file so a real GEMINI_API_KEY in .env is not used.
printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 16)" > /tmp/ra-test.env
docker build -t resume-analyzer-api:local backend && docker build -t resume-analyzer-web:local frontend
docker compose --env-file /tmp/ra-test.env -p ra-fakeai -f compose.yaml -f compose.fake-ai.yaml up --build -d --wait
python3 -I scripts/smoke_test_stack.py http://localhost:8090
(cd frontend && E2E_BASE_URL=http://localhost:8090 npx playwright test)
docker compose --env-file /tmp/ra-test.env -p ra-fakeai -f compose.yaml -f compose.fake-ai.yaml down --volumes

# CI configuration
docker run --rm -v "$PWD:/repo:ro" -w /repo rhysd/actionlint:1.7.8
```

## 20. Confirmation of what was not done

- No deployment to Vercel, Render or anywhere else; no Render/Vercel project or Blueprint created.
- No `git add`, commit, push, branch switch or history change.
- No live Gemini call. The production-mode containers used a placeholder key on networks without internet
  access. The root `.env` (which contains a key) was never passed to any container: every Compose run used a
  separate env file.
- No production database or credential; all databases were throwaway containers or a scratch SQLite file, and
  all were deleted (no `ra-m9*` containers, networks or volumes remain).
- No security control was weakened, no test removed, no assertion reduced, no timeout raised.
- No new application feature. Code changes in this milestone: type annotations in one test file, and one CI
  line (`mypy app tests scripts`).

**Files changed in Milestone 9:** created `docs/milestone-9-final-audit.md`, `docs/milestone-9-final-report.md`.
Updated `README.md`, `docs/deployment-architecture.md`, `docs/deploy-docker.md`, `docs/deploy-render.md`,
`docs/deploy-vercel.md`, `docs/refactoring-plan.md`, `docs/gemini-verification-plan.md`,
`backend/tests/integration/test_deployment.py`, `.github/workflows/backend.yml`. Reviewed without changes:
`.env.example`, `backend/.env.example` (complete and consistent with `Settings`), `render.yaml`,
`frontend/vercel.json`, Compose files, Dockerfiles.

Verification scripts used for §9 (the production start-up checks, the access-key probe, the TLS edge and the
PDF fetch probe) were kept outside the repository, in the session's scratch directory, and are not part of
the deliverable.

## 21. Follow-up: PDF resource-fetcher fix (approved 2026-11-11)

**Change (narrow, no rendering redesign).** `app/documents/render.py`: `render_pdf` now passes
`_refusing_url_fetcher(weasyprint)`, an instance of a `weasyprint.URLFetcher` subclass (the WeasyPrint 70
interface) whose `fetch` always raises the existing refusal (`_refuse_fetch`). It never calls the base
implementation; as defence in depth it is also built with `allowed_protocols=()` (every scheme refused) and
`allow_redirects=False`. `fail_on_errors=False` makes WeasyPrint treat a refusal as a skipped resource with a
warning, instead of reading a missing attribute and crashing. The policy is unchanged: every URL is refused,
including `http(s):`, `file:` and `data:`. `pyproject.toml`: the existing mypy override for `weasyprint` now also
covers `weasyprint.*` (the tests import `weasyprint.urls`).

**New tests** (`tests/integration/test_rewrite_exports.py::TestPdfResourceFetcher`, 11, need Pango):

| Test | Asserts |
|---|---|
| `test_fetcher_uses_the_weasyprint_interface` | Instance of `weasyprint.URLFetcher`; `fail_on_errors` false; no allowed protocols |
| `test_every_url_is_refused_without_opening_it` × 4 (`http`, `https`, `file`, `data`) | `fetch()` and `__call__` raise the refusal with `open()` patched to fail the test; WeasyPrint's own `fetch()` path raises `URLFetchingError`, **not** `AttributeError` |
| `test_hostile_html_renders_without_any_fetch` | Ten hostile cases (stylesheet link, `@import`, `@font-face`, CSS background, http/https images, iframe/object, local-file stylesheet and images incl. `/etc/passwd`, `data:` stylesheet) rendered through `render_pdf`: a PDF is produced with the page text; the fetcher was consulted and refused; a local listening socket received **0** connections; a secret-marker file, `/etc/passwd` and the `data:` content never appear in the PDF |
| `test_normal_exports_never_need_the_fetcher` × 5 templates | Real export renders, contains the name, and **never** consults the fetcher |

**Regression proof.** With the old plain-function fetcher temporarily restored, the end-to-end test fails
with `AttributeError: 'function' object has no attribute '_fail_on_errors'`; with the fix it passes.

**Results after the fix:**

| Check | Result |
|---|---|
| `ruff check`, `ruff format --check`, `mypy app tests scripts` (strict) | ✅ clean (135 files) |
| Backend, SQLite | ✅ **820 passed, 1 skipped** (809 + 11 new) |
| Backend, PostgreSQL 16.15 | ✅ **821 passed** (810 + 11 new) |
| Rebuilt production and fake-AI images | ✅ |
| Export suites inside the Linux image, network disabled | ✅ 95 passed (both export test files, incl. the 11 new), 0 skipped |
| Hostile-HTML probe in the production image (previously `AttributeError`) | ✅ a PDF is produced in all three groups; 0 connection attempts; no `/etc/passwd` content |
| Fake-AI Compose stack: smoke test incl. 5 templates × PDF and DOCX | ✅ 38/38, four times; PDF sizes identical to before the fix |
| Container logs | ✅ 0 errors, 0 fetcher warnings (normal exports never consult it) |
| Playwright, default mode | ✅ 16/16 |
| Playwright against the containers | ⚠️ the **first** run after the fix reported **15 passed** in 1.1 min (retries are 0, so one test failed). Its output was not captured; the API logs of that run show no errors. **Six further runs passed 16/16** (24–56 s), three of them repeating the exact sequence (fresh stack → smoke test → Playwright). Cause undetermined. The most likely explanation is a timing failure while the machine was loaded (a test suite and image builds were running in parallel; the run took about twice the usual time). It is not plausibly the fetcher change, which normal exports never reach. Worth watching on the first GitHub-hosted runs |
| Frontend | Unchanged; not re-run |

Nothing was deployed, staged, committed or pushed; no live Gemini call; all throwaway containers and volumes
removed. Files changed in the follow-up: `backend/app/documents/render.py`,
`backend/tests/integration/test_rewrite_exports.py`, `backend/pyproject.toml`, and these documents.

