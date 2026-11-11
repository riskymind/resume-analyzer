# Authentication, Sessions and Data Ownership

_Applies from Milestone 2b. Audience: developers and operators of this project._

## 1. Overview

| Concern | Implementation | Code |
|---|---|---|
| Passwords | Argon2id (`argon2-cffi`). Default cost t=3, m=64 MiB, p=4 (RFC 9106). Hashes are upgraded transparently at login when the parameters change. Unknown-email logins still spend a full hash verification, so response timing does not reveal which emails exist. | `app/core/security.py` |
| Sessions | Server-side rows in `sessions`. The cookie carries 256 random bits (`secrets.token_urlsafe(32)`); the database stores only its SHA-256. Absolute lifetime `SESSION_TTL_HOURS` (default 168h) plus idle timeout `SESSION_IDLE_TIMEOUT_HOURS` (default 24h). | `app/services/auth.py` |
| Rotation | Every successful login or registration issues a new token, and the session named by any presented cookie is deleted first. This prevents session fixation. | `issue_session` |
| Logout | Deletes the session row (other devices stay signed in) and clears the cookie. | `POST /api/v1/auth/logout` |
| Cookie | `HttpOnly; SameSite=Lax; Path=/; Max-Age=<ttl>`. When secure (`COOKIE_SECURE`, always on in production), it adds `Secure` and the `__Host-` name prefix, so the browser rejects any `Domain` attribute and the cookie belongs to exactly one origin. | `app/api/routes/auth.py` |
| CSRF | Two independent checks on every state-changing authenticated request: (1) the `Origin` (or `Referer`) must be a trusted frontend origin or the API's own origin; (2) `X-CSRF-Token` must equal the synchronizer token bound to the session. Login and registration also get the origin check (login CSRF). SameSite is defence in depth, not the control. | `app/api/deps.py` |
| Authorization | Every analysis query filters on the signed-in user's id in SQL (`app/repositories/analyses.py`). Another user's record returns the same 404 as a missing one. | |
| Rate limits | Fixed-window counters in the `rate_limits` table, updated with one atomic upsert per hit. They are shared by all workers and instances through the database; nothing lives in process memory. Keys are SHA-256 digests, so emails and IPs are not stored. | `app/services/rate_limit.py` |
| Account deletion | `DELETE /api/v1/auth/me` with `{"password": ..., "confirmation": "delete my account"}` plus CSRF. Explicitly deletes the user's analyses (including stored resume and job-description text), resumes, quality reports, all sessions, and the user, in one transaction, then verifies nothing owned remains. Foreign keys with `ON DELETE CASCADE` are a second safety net. | `delete_account` |

### Endpoints

| Method | Path | Auth | CSRF |
|---|---|---|---|
| POST | `/api/v1/auth/register` | — | Origin check |
| POST | `/api/v1/auth/login` | — | Origin check |
| POST | `/api/v1/auth/logout` | session (if any) | ✔ |
| GET | `/api/v1/auth/me` | ✔ | — |
| DELETE | `/api/v1/auth/me` | ✔ | ✔ |
| POST | `/api/analyze` | ✔ | ✔ |
| GET | `/api/analyses`, `/api/analyses/{id}` | ✔ | — |
| POST | `/api/v1/resumes` | ✔ | ✔ |
| GET | `/api/v1/resumes`, `/api/v1/resumes/{id}` | ✔ | — |
| DELETE | `/api/v1/resumes/{id}` | ✔ | ✔ |
| GET | `/api/v1/resumes/{id}/document`, `/api/v1/rewrites`, `/api/v1/rewrites/templates`, `/api/v1/rewrites/{id}`, `/api/v1/rewrites/{id}/preview` | ✔ | — |
| POST | `/api/v1/rewrites`, `/api/v1/rewrites/{id}/regenerate`, `/api/v1/rewrites/{id}/export` | ✔ | ✔ |
| PATCH / DELETE | `/api/v1/rewrites/{id}` | ✔ | ✔ |

The original `/api/analyze` and `/api/analyses` request and response shapes are unchanged. The one
contract change is that they now require a session (otherwise `401 not_authenticated`).

### Default rate limits

| Limit | Default | Setting |
|---|---|---|
| Login attempts per client IP | 20 / 15 min | `LOGIN_MAX_ATTEMPTS_PER_IP` |
| Login attempts per email (case-insensitive) | 10 / 15 min | `LOGIN_MAX_ATTEMPTS_PER_EMAIL` |
| Registrations per client IP | 5 / hour | `REGISTER_MAX_PER_IP` |
| AI analyses per user | 5 / minute | `AI_MAX_REQUESTS_PER_MINUTE` |
| AI analyses per user | 50 / day | `AI_MAX_REQUESTS_PER_DAY` |
| Resume exports (PDF/DOCX) per user | 10 / minute | `EXPORT_MAX_PER_MINUTE` |

Rewrite generation and regeneration count against the AI limits above.

All limits return `429` with error code `rate_limited` and a `Retry-After` header. Attempts are
counted before the password check and committed in their own transaction, so failed logins count.
Invalid uploads are rejected before the AI limit is touched and do not use up quota.

## 2. Deployment configuration

The browser only ever talks to **one origin**, the frontend's. `/api/*` is proxied to the backend
(Vite in development, nginx in Docker, a Vercel rewrite in production). The session cookie is
therefore first-party, and no cross-site cookie (`SameSite=None`) or CORS credential sharing is
needed.

| Environment | Browser origin | Required backend settings |
|---|---|---|
| Local (`npm run dev` + `uvicorn`) | `http://localhost:5173` | Defaults work: `CORS_ORIGINS=http://localhost:5173`, non-secure `ra_session` cookie over plain HTTP. |
| Docker Compose (Milestone 8) | `http://localhost:8080` (nginx) | `CORS_ORIGINS=http://localhost:8080`, `COOKIE_SECURE=false` (no TLS locally). nginx must pass `Host`, `Cookie`, `Origin` and `X-Forwarded-*` through. |
| Render backend + Vercel frontend | `https://<app>.vercel.app` (and any custom domain) | `APP_ENV=production` (forces secure `__Host-ra_session` cookies), `CORS_ORIGINS=https://<app>.vercel.app[,https://custom.domain]`. Start uvicorn with `--proxy-headers --forwarded-allow-ips='*'`. |
| Render only (static site + API) | `https://<static>.onrender.com` | As above, with that origin in `CORS_ORIGINS`. |

`CORS_ORIGINS` does double duty. It lists the frontend origins allowed to call the API directly
(CORS), and the origins trusted by the CSRF origin check. In production the app refuses to start
if it contains a non-HTTPS origin or `*`.

**Vercel rewrite requirements.** The rewrite (`/api/:path*` → `https://<api>.onrender.com/api/:path*`)
must forward the `Cookie`, `Origin`, `X-CSRF-Token` and `Content-Type` request headers and return
`Set-Cookie` unchanged. That is standard for Vercel external rewrites. The cookie has no `Domain`
attribute, so the browser stores it for the Vercel origin and sends it back on every `/api` call.

## 3. Assigning existing history to an account

Analyses created before accounts existed have no owner and are visible to nobody. They are
**never** assigned automatically. Run these from `backend/` with the same `DATABASE_URL` as the
server.

```bash
# 1. Register the account in the app first, then inspect what would change:
python -m app.cli list-unowned
python -m app.cli assign-history --email you@example.com --dry-run

# 2. Assign (prompts you to type "assign"; add --ids 3,7 to assign a subset):
python -m app.cli assign-history --email you@example.com
```

What the command does:

1. Refuses if the account does not exist or the schema is not migrated.
2. Refuses if any requested id already has an owner. Owned rows are never reassigned.
3. **Backup.** On SQLite it writes a consistent online copy to `backend/data/backups/resume_analyzer-<timestamp>.db`
   before changing anything. On PostgreSQL it cannot run `pg_dump` for you: take a backup
   (`pg_dump --format=custom --file=backup.dump "$DATABASE_URL"`, or a Render on-demand backup) and
   pass `--postgres-backup-confirmed`.
4. Updates the rows in one transaction, aborting if the number changed differs from what was shown.
5. Re-reads the rows to verify ownership, then writes a rollback manifest
   (`history-assignment-<timestamp>.json`: ids, user id and backup path, no document content).

**Rollback**, either way:

```bash
# Row-level: return exactly the assigned rows to "unowned" (rows reassigned since are left alone)
python -m app.cli rollback-history-assignment --manifest data/backups/history-assignment-<ts>.json

# Full restore (SQLite): stop the server, then
cp data/backups/resume_analyzer-<ts>.db data/resume_analyzer.db
# Full restore (PostgreSQL): pg_restore --clean --dbname "$DATABASE_URL" backup.dump
```

## 4. What is verified, and what is assumed

| Claim | Status |
|---|---|
| Registration, login, logout, rotation, fixation, expiry (absolute and idle), CSRF, origin checks, rate limits, isolation, deletion and atomicity | Automated tests (SQLite) |
| Session survives a backend restart | Automated test, and live with real uvicorn through the Vite proxy |
| Cookie, CSRF, logout and 429 behaviour through a reverse proxy | Live: real uvicorn behind the Vite dev proxy with curl as the browser (Milestone 2b report) |
| History assignment on a real legacy database | Live on a copy of the developer's actual `resume_analyzer.db` (original untouched) |
| Rate limits shared across instances | Automated test with two app instances on one database. **PostgreSQL concurrency not yet exercised** (no Postgres available locally; CI runs the suite against Postgres in Milestone 8). |
| Docker / nginx proxy | **Not yet tested.** Docker is added in Milestone 8. |
| Vercel rewrite → Render with `__Host-` cookies | **Not tested.** Requires a deployment, which is not authorized. Based on documented Vercel rewrite behaviour. |

### Known limitations

- **Client IP behind proxies.** Per-IP limits use the address uvicorn resolves from
  `X-Forwarded-For`. With `--forwarded-allow-ips='*'`, a client that reaches the Render URL
  directly, bypassing Vercel, can forge that header and dodge the **per-IP** login and registration
  limits. The per-email login limit and the per-user AI limits do not depend on the IP. A future
  hardening step is to accept API traffic only from the proxy (for example a shared-secret header
  added by the rewrite).
- **No email verification or password reset.** Both need an email provider. Registration reveals
  that an email is already registered (`409`); this is rate-limited per IP.
- **Fixed windows** allow up to 2× the limit across a window boundary. That is acceptable for abuse
  and cost control at this scale.
