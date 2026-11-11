# Deploying the API to Render

_Milestone 8, reviewed in Milestone 9 · audience: whoever sets up the production backend. Nothing in this
repository deploys by itself; every step below is manual and needs an authorized Render account._

> **Verification status.** `render.yaml` validates against Render's published schema, and the image's
> production behaviour has been tested locally (start-up refusal, `$PORT`, access key, migrations, graceful
> shutdown; [milestone-9-final-report.md](milestone-9-final-report.md)). **The Blueprint has never been
> applied to Render**, and the Render CLI's `render blueprints validate` has not been run. Render builds from
> the GitHub repository, so the code must be committed and pushed first. Full first-deployment order:
> [milestone-9-final-report.md §18](milestone-9-final-report.md#18-first-deployment-checklist).

The Blueprint [`render.yaml`](../render.yaml) defines:

| Resource | Type | Key settings |
|---|---|---|
| `resume-analyzer-api` | Web service, `runtime: docker` | `dockerContext: ./backend`, `dockerfilePath: ./backend/Dockerfile`, plan `free` (private preview; see §3), region `oregon`, `healthCheckPath: /api/v1/health`, migrations at start-up (`RUN_MIGRATIONS_ON_START=true`), `autoDeployTrigger: "off"`, default 30 s shutdown delay (`maxShutdownDelaySeconds` is not supported on free), `buildFilter` on `backend/**` |
| `resume-analyzer-db` | PostgreSQL 16 | plan `free` (1 GB, no backups, expires after 30 days), region `oregon`, database `resume_analyzer`, user `resume`, `ipAllowList: []` (no external connections) |

The frontend is deployed to Vercel ([deploy-vercel.md](deploy-vercel.md)); browsers never call the Render
URL directly.

## 1. Environment variables

| Variable | Source in `render.yaml` | Notes |
|---|---|---|
| `APP_ENV` | `production` | Enforces PostgreSQL, HTTPS origins, `Secure` `__Host-` cookies, a Gemini key; disables `/api/docs`. |
| `DATABASE_URL` | `fromDatabase.connectionString` | Internal URL (private network). `postgres://` is normalised to the psycopg 3 driver. |
| `GEMINI_API_KEY` | `sync: false` (**secret, entered in the dashboard**) | Server-side only. |
| `AI_CALLS_ENABLED` | `false` | Kill switch. While `false` no Gemini client is built: no generation or embedding call leaves the server, AI routes answer 503 `ai_not_configured`, and readiness reports `ai_provider: disabled` (still 200). Set `true` in the dashboard only once live AI usage is authorized; re-syncing the Blueprint resets it to `false`. |
| `CORS_ORIGINS` | `sync: false` (**entered in the dashboard**) | The public HTTPS origin(s) of the Vercel frontend, comma-separated, e.g. `https://resume-analyzer.vercel.app,https://resume.example.com`. It is also the CSRF origin allow-list, so it must contain every domain users browse. |
| `BACKEND_ACCESS_KEY` | `generateValue: true` (**secret**) | **Required in production**: without it the API refuses to start (fail closed). Generated once by Render when the Blueprint is first applied; never hard-coded. Copy it into the Vercel project as a server-only variable. The API answers 403 to anything that does not carry it; the only exception is the liveness probe `/api/v1/health`. |
| `FORWARDED_ALLOW_IPS` | `*` | uvicorn trusts `X-Forwarded-For`. Safe only because the access key guarantees every request came through Vercel, which overwrites that header with the real client IP. Per-IP login/registration limits depend on it. |
| `WEB_CONCURRENCY` | `1` | One uvicorn process (requests still run concurrently in its thread pool). Raise it on larger plans; Argon2 uses 64 MiB per concurrent login. |
| `GRACEFUL_SHUTDOWN_SECONDS` | `25` (free plan) | Must fit Render's default 30 s SIGTERM→SIGKILL window, because free services cannot set `maxShutdownDelaySeconds`. An AI request still running at shutdown (they can take up to 90 s) may be cut off; the client sees an error and can retry. On paid plans use `100` with `maxShutdownDelaySeconds: 120`. |
| `LOG_LEVEL` | `INFO` | Logs are JSON on stdout (Render's log stream). |
| `RUN_MIGRATIONS_ON_START` | `true` (free plan only) | The entrypoint runs `python -m app.cli migrate` (advisory-locked) before uvicorn, replacing `preDeployCommand`, which free instances lack. Remove it when moving to a paid plan. |
| `PORT` | injected by Render | The entrypoint binds `0.0.0.0:$PORT`. |

Optional tuning variables (limits, timeouts, model names) are documented in
[`backend/.env.example`](../backend/.env.example) and can be added in the dashboard.

## 2. First deployment (manual)

1. Render dashboard → **New → Blueprint** → connect the GitHub repository and pick the branch.
2. Render shows the two resources from `render.yaml`. Enter `GEMINI_API_KEY` and `CORS_ORIGINS` when it
   prompts for the `sync: false` values. For `CORS_ORIGINS`, use the Vercel production URL; if it is not
   known yet, enter a placeholder HTTPS origin and update it after step 1 of the Vercel guide.
3. **Apply**. Render creates the database, builds the image from `backend/Dockerfile`, and starts the
   service; on the free plan the container migrates at start-up before serving (on paid plans, the
   pre-deploy migration runs in a one-off instance of the new image first; see §3). Deploys stay manual
   afterwards (`autoDeployTrigger: "off"`).
4. Copy the generated `BACKEND_ACCESS_KEY` (service → Environment) into Vercel.
5. Verify (§4).

Later deploys: service → **Manual Deploy → Deploy latest commit**. Once CI is trusted, `autoDeployTrigger`
can be changed to `checksPass`. That is a deliberate change, not done here.

## 3. Migrations

- Paid plans: `preDeployCommand: python -m app.cli migrate` runs **once per deploy, before** the new version
  takes traffic. If it fails, the deploy stops and the previous version keeps serving. Free plan (current
  Blueprint): `RUN_MIGRATIONS_ON_START=true` instead, below.
- The command holds a PostgreSQL advisory lock for the whole upgrade, so it can never run twice concurrently.
  A second runner waits, then finds nothing to do (tested with four concurrent runners).
- `AUTO_MIGRATE` is off in production, so web processes never migrate.
- Migrations are additive and were tested for upgrade from empty, idempotency, and full downgrade/upgrade round
  trips on PostgreSQL 16 (CI job `test-postgres`). Nothing in the Blueprint resets or drops data.
- Take a backup before risky migrations (Render dashboard → database → Backups, or
  `pg_dump --format=custom "$EXTERNAL_DATABASE_URL"`; external access must then be allowed temporarily in
  `ipAllowList`).

**Current Blueprint: free plans (private preview).** Free instance types do not support `preDeployCommand`,
so `render.yaml` sets `RUN_MIGRATIONS_ON_START=true` instead: the entrypoint migrates (advisory-locked) before
uvicorn starts. A failed migration means the new instance never becomes healthy, so the deploy fails.
Free-plan limits (Render docs, checked 2026-11-11): the web service sleeps after 15 idle minutes (~1 min cold
start) and has no SSH/shell; the database is 1 GB, has **no backups**, and **expires 30 days after creation**
(deleted after a further 14 days unless upgraded); one free database per workspace. Fictional data only.

**Before real users**, switch to paid plans: web `plan: starter` (or higher), restore
`preDeployCommand: python -m app.cli migrate`, remove `RUN_MIGRATIONS_ON_START`, restore
`maxShutdownDelaySeconds: 120` with `GRACEFUL_SHUTDOWN_SECONDS=100`, and database
`plan: basic-256mb` (or higher), then configure backups.

## 4. Verify after deploying

```bash
API=https://resume-analyzer-api.onrender.com        # the service URL shown by Render
curl -s $API/api/v1/health                          # {"status":"ok"}  (the only path exempt from the key)
curl -s -o /dev/null -w '%{http_code}\n' $API/api/v1/health/ready   # 403: direct access is refused
curl -s -H "X-Backend-Access-Key: $KEY" $API/api/v1/health/ready    # {"status":"ok","checks":{...}}
```

Then check through the frontend as described in [deploy-vercel.md §4](deploy-vercel.md#4-verify-after-deploying).
In the service logs, the first lines are the configuration summary (`Configuration OK (APP_ENV=production)`,
`backend access key: required`, the database password masked).

## 5. Dashboard-only settings and limitations

| Item | Why it is not in `render.yaml` |
|---|---|
| Secret values (`GEMINI_API_KEY`, `CORS_ORIGINS`) | Never committed; `sync: false` prompts for them. |
| Custom domain for the API | Not needed: browsers reach the API through Vercel. |
| Database backups / point-in-time recovery | Depend on the database plan; configure in the dashboard. |
| Alerts / notifications | Account-level settings. |
| Retention purge cron job | **Not implemented** in the application (no purge command exists), so no cron job is defined. Users can delete their data and account in the app. |

The plan names (`free` for the private preview; `starter` / `basic-256mb` recommended for real use, see §3)
and the region are defaults; adjust them before the first apply.
The database's `region`, `databaseName`, `user` and `postgresMajorVersion` cannot be changed after creation.

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Configuration error: … BACKEND_ACCESS_KEY must be set in production` | The generated variable was deleted or the service was created outside the Blueprint. Add it (Environment → Generate), then update Vercel to match. |
| Deploy fails in pre-deploy with `Configuration error:` | The listed variable is missing or invalid (often `CORS_ORIGINS` not HTTPS). |
| Health check fails, logs show `Configuration error` | Same as above; the service never starts with invalid configuration. |
| Every request from the website returns 403 `forbidden` | Vercel's `BACKEND_ACCESS_KEY` does not match Render's, or is missing. |
| Sign-in works, every change fails with `origin_not_allowed` | The browsed origin is missing from `CORS_ORIGINS` (add custom domains too). |
| All users share one login rate limit | `FORWARDED_ALLOW_IPS` is not `*`, so the proxy's address is used as the client IP. |
| Requests fail after ~100 s with 504 | A proxy timeout in front of the API. AI calls are bounded by `AI_TOTAL_TIMEOUT_SECONDS` (90 s); keep it below the proxy limits. |
