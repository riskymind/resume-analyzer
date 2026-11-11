# Docker and Docker Compose

_Milestone 8, re-verified in Milestone 9 (2026-11-11) · audience: developers running the stack locally or
reviewing the images._

## 1. Images

| Image | Dockerfile (context) | Base | Runs as | Port | Size (measured) |
|---|---|---|---|---|---|
| API (production) | `backend/Dockerfile` (`backend/`), default target | `python:3.12.16-slim-bookworm` | `app` (uid 10001) | `$PORT` (8000) | 542 MB |
| API + CJK fonts | same, `--build-arg INSTALL_CJK_FONTS=true` (default `false`) | same | same | same | 712 MB; without it, PDFs render CJK as empty boxes ([report §12](milestone-8-completion-report.md#12-image-sizes-and-the-cjk-font-decision)) |
| API test image | same, `--target fake-ai` | production image + test suite + dev tools | same | 8000 | **test only, never deploy** |
| Web (production) | `frontend/Dockerfile` (`frontend/`), target `runtime` | `nginxinc/nginx-unprivileged:1.28.2-alpine` | `nginx` (uid 101) | 8080 | 82 MB |
| Web (development) | same, target `dev` | `node:24.22.2-alpine` | root (dev only) | 5173 | — |

**API image.** A builder stage installs the pinned `requirements.txt` (wheels only) into `/opt/venv`; the
runtime stage adds the WeasyPrint system libraries and the template fonts (Carlito, Caladea, Liberation,
DejaVu), copies the venv and `app/`, and drops to the unprivileged user. Code is root-owned and read-only for
that user. The only writable paths are `/app/data` (SQLite fallback, unused with PostgreSQL) and `/tmp`.
`.dockerignore` keeps `.env*`, `data/`, `*.db`, virtualenvs and caches out of the build context, so none of
them can reach an image. The image's `APP_ENV` defaults to `production`, so a container started without
configuration fails at once with a readable list of what is missing.

**Entrypoint** (`backend/docker-entrypoint.sh`):

1. `python -m app.cli check-config` validates the configuration exactly as the server would. It prints a
   summary with the database password masked, or `Configuration error:` plus one line per problem (never the
   values), and exits 1.
2. If `RUN_MIGRATIONS_ON_START=true`, it runs `python -m app.cli migrate` (off by default).
3. `exec uvicorn app.main:app` on `0.0.0.0:$PORT` with `--proxy-headers`, `--forwarded-allow-ips
   $FORWARDED_ALLOW_IPS` (default `127.0.0.1`), `--workers $WEB_CONCURRENCY` (default 1) and
   `--timeout-graceful-shutdown $GRACEFUL_SHUTDOWN_SECONDS` (default 25). Because of `exec`, uvicorn is PID 1
   and receives SIGTERM itself: in-flight requests finish, the lifespan shutdown runs, and the process exits 0.

Any other command is run as given: `docker run IMAGE python -m app.cli migrate`.

**Web image.** `npm ci` + `npm run build`, then only `dist/` is copied into nginx (no Node, no
`node_modules`). nginx renders `nginx/default.conf.template` at start-up, using `API_UPSTREAM` (default
`http://api:8000`):

| Path | Behaviour |
|---|---|
| `/api/*` | Proxied to the API. Never falls back to `index.html`, so API errors stay JSON. `X-Forwarded-For` is **overwritten** with the client address (no spoofing), timeouts 120 s, bodies up to 13 MB. |
| `/assets/*` | Served from disk with a one-year immutable cache. A missing file is a 404, not HTML. |
| anything else | The file if it exists, otherwise `index.html` (SPA fallback for `/rewrites/<id>`, `/resumes/<id>`, …). |
| `/healthz` | nginx liveness for the container health check. |

Security headers (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`) match
`vercel.json`.

## 2. Compose stacks

| File(s) | Purpose | URL |
|---|---|---|
| `compose.yaml` | **Production-like**: production images, PostgreSQL, explicit migrations, nginx, no source mounts | http://localhost:8080 |
| `compose.yaml` + `compose.dev.yaml` | **Development**: API with `--reload` and bind-mounted `backend/app`, Vite dev server with the mounted `frontend/`, PostgreSQL published on 127.0.0.1:5433 | http://localhost:5173 (API: :8000) |
| `compose.yaml` + `compose.fake-ai.yaml` (own project name) | **Isolated test**: like the production-like stack, but the API is the `fake-ai` image (canned AI answers) and data lives in its own volume | http://localhost:8090 |

Services in `compose.yaml`:

```
db (postgres:16.15, volume pgdata, network "data" only)
 └─healthy─► migrate (one-shot: python -m app.cli migrate; exits 0)
              └─completed─► api (2 workers, network "data" + "web", not published)
                             └─healthy─► web (nginx, 127.0.0.1:8080)
```

- The `data` network is `internal`: PostgreSQL has no route to or from outside the stack and is not published
  (except by `compose.dev.yaml`, on 127.0.0.1 only).
- Migrations run once, from the `migrate` service, before any API process starts; the API itself does not
  migrate (`AUTO_MIGRATE=false`). The command is advisory-locked on PostgreSQL, so re-running it while the API
  is up is safe: `docker compose run --rm migrate`.
- Ports bind to 127.0.0.1 only. Defaults avoid common local services (8080, 5173, 8000, 5433, 8090); all can
  be changed in `.env`.

## 3. Commands

```bash
cp .env.example .env                  # set POSTGRES_PASSWORD (openssl rand -hex 16); GEMINI_API_KEY optional

# Production-like
docker compose up --build             # add -d to detach; --wait to block until healthy
docker compose ps                     # db/api/web "healthy", migrate "Exited (0)"
curl -s localhost:8080/api/v1/health/ready

# Development
docker compose -f compose.yaml -f compose.dev.yaml up --build

# Logs, shell, database
docker compose logs -f api
docker compose exec api python -m app.cli check-config
docker compose exec db psql -U resume -d resume_analyzer

# Stop (data is KEPT in the pgdata volume)
docker compose down

# Delete all local data, explicitly and irreversibly
docker compose down --volumes
```

Without `GEMINI_API_KEY`, everything works except the AI-backed actions, which answer 503
"AI analysis is not configured", and `/api/v1/health/ready` reports `degraded` (`ai_provider:
not_configured`). The container health check uses liveness, so the stack is still healthy.

### Isolated fake-AI run (no credentials, no AI credits)

```bash
export POSTGRES_PASSWORD=$(openssl rand -hex 16)
docker compose -p resume-analyzer-fakeai -f compose.yaml -f compose.fake-ai.yaml up --build -d --wait
python3 -I scripts/smoke_test_stack.py http://localhost:8090                          # API-level journey
(cd frontend && E2E_BASE_URL=http://localhost:8090 npx playwright test)              # browser journey
docker compose -p resume-analyzer-fakeai -f compose.yaml -f compose.fake-ai.yaml down --volumes
```

The fake provider answers only for the synthetic sample resume and job description
(`frontend/e2e/fixtures/`). It refuses to start with `APP_ENV=production`, and its image is never used by
`render.yaml`.

## 4. Why the Compose API runs with `APP_ENV=development`

Production mode requires HTTPS `CORS_ORIGINS` (the list is also the CSRF origin allow-list) and `Secure`
cookies. A local stack on `http://localhost:8080` cannot meet that without weakening the check, which was not
done. The Compose stack therefore uses the production **image** and production-like **settings** (PostgreSQL,
JSON logs, explicit migrations, proxy-header handling, 2 workers), but `APP_ENV=development`. As a result,
`/api/docs` is available and cookies are `ra_session` rather than `__Host-ra_session`.

The image's real production mode is verified separately, by starting it with a complete production
configuration against PostgreSQL (CI job `images`, and the completion report §4).

**Milestone 9: production-mode topology test.** To close as much of this gap as possible without weakening
the HTTPS or origin checks, the unmodified production images were run as
`TLS edge → web (nginx) → api (APP_ENV=production) → PostgreSQL 16`. The edge is a local nginx that terminates
TLS (self-signed certificate for `localhost`), overwrites `X-Forwarded-For` and injects
`X-Backend-Access-Key`, emulating the Vercel router. `CORS_ORIGINS=https://localhost:8443`. Every network except
the edge's was `internal`, so the API had no route to the internet and could not call Gemini. Results (smoke
test `--no-ai` 20/20 over HTTPS, 31 access-key probes, cookie/CSRF/CORS checks, log scan):
[milestone-9-final-report.md §9](milestone-9-final-report.md#9-production-access-key-verification). The
script is not part of the repository. This emulation is not Vercel: real Vercel behaviour still has to be
checked on the first deployment ([deploy-vercel.md §4](deploy-vercel.md#4-verify-after-deploying)).

**Keeping your `.env` out of test runs.** Compose reads the root `.env` automatically. If it contains a real
`GEMINI_API_KEY`, the production-like stack makes billable calls. For throwaway runs, point Compose at a
separate file: `docker compose --env-file /path/to/test.env …` (it replaces `.env`; put only
`POSTGRES_PASSWORD=…` in it). The fake-AI override already blanks the key for the API.

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `required variable POSTGRES_PASSWORD is missing a value` | Create `.env` from `.env.example` and set it. |
| `migrate` exits 1, `password authentication failed` | The volume was created with a different password. Use the original password, or reset the data: `docker compose down --volumes`. |
| `api` restarts with `Configuration error: …` | Read the listed variables; `docker compose logs api` shows the full message. |
| `dependency failed to start: … unhealthy` | `docker compose logs <service>`; `docker inspect --format '{{json .State.Health}}' <container>`. |
| Port already in use | Set `WEB_PORT` / `DEV_WEB_PORT` / `API_PORT` / `DB_PORT` in `.env`. |
| Sign-in works but every change fails with "Request origin is not allowed" | The browser origin is not in `CORS_ORIGINS`. The stack allows `http://localhost:$WEB_PORT` and `http://127.0.0.1:$WEB_PORT`; use one of these. |
| Dev server does not reload on macOS | File events from bind mounts can be delayed; restart the service, or run Vite on the host (`npm run dev`). |
| PDF export returns 503 | Pango missing. This cannot happen in the image; outside Docker see [export-qa.md §5](export-qa.md). |
