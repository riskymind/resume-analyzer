# Deploying the Frontend to Vercel

_Milestone 8, reviewed in Milestone 9 · audience: whoever sets up the production frontend. Nothing here
deploys automatically; every step is manual and needs an authorized Vercel account._

> **Verification status.** `vercel.json` validates against Vercel's published schema, and a unit test
> emulates its route order. The same routing contract (API proxy, SPA fallback, asset 404s, security headers)
> works in the nginx image, and a local TLS proxy that injects the key, standing in for Vercel, was
> tested in Milestone 9. **Vercel itself has never been exercised.** In particular, the
> `env` expansion of `${BACKEND_URL}`, the `request.headers` transform, cookie pass-through, 12 MB request
> bodies and the external-rewrite time limit (AI calls can take up to 90 s) are unverified. Run §4 on the
> first preview deployment. Full order:
> [milestone-9-final-report.md §18](milestone-9-final-report.md#18-first-deployment-checklist).

The frontend is a static Vite build. Vercel serves it and forwards `/api/*` to the Render API, so the browser
only ever talks to one origin. That keeps the session cookie first-party and removes the need for CORS. The
configuration is [`frontend/vercel.json`](../frontend/vercel.json).

## 1. Project settings

| Setting | Value |
|---|---|
| Root Directory | `frontend` |
| Framework preset | Vite (also set in `vercel.json`) |
| Install / Build command | `npm ci` / `npm run build` (from `vercel.json`) |
| Output directory | `dist` |
| Node.js version | 24.x (matches CI and the Docker build) |

## 2. Environment variables

| Variable | Kind | Value | Exposed to the browser? |
|---|---|---|---|
| `BACKEND_URL` | Server-side (routing) | The Render service origin, e.g. `https://resume-analyzer-api.onrender.com`. No trailing slash, no `/api`. | **No.** It is expanded by Vercel's router (`"env": ["BACKEND_URL"]`), never compiled into the bundle. |
| `BACKEND_ACCESS_KEY` | **Secret** (mark it *Sensitive*), **required** | The value Render generated for the API's `BACKEND_ACCESS_KEY` (the API cannot run in production without it). Never prefix it `VITE_`/`NEXT_PUBLIC_`. | **No.** Vercel adds it as the `x-backend-access-key` request header on the way to Render. The browser neither sends nor sees it. |

Set both for **Production** (and **Preview**, if previews should reach a backend; preview origins must then
also be listed in the API's `CORS_ORIGINS`).

There are **no** `VITE_*` variables: the bundle calls the relative path `/api`. Do not add
`VITE_API_BASE_URL` in production. Anything prefixed `VITE_` is embedded in public JavaScript, and a
cross-origin API URL would also break the first-party cookie design.

## 3. Routing (`vercel.json`)

`vercel.json` uses Vercel's `routes` syntax, because the simpler `rewrites` cannot read environment
variables or set request headers. The routes run in this order:

| # | Match | Effect |
|---|---|---|
| 1 | every path | Security headers (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`), then continue |
| 2 | `/api/(.*)` | Proxy to `${BACKEND_URL}/api/$1` with `x-backend-access-key: $BACKEND_ACCESS_KEY` set (overwriting any client-sent value). **Stops here**, so API paths can never reach the SPA fallback. |
| 3 | `/assets/(.*)` | One-year immutable cache header, then continue |
| 4 | `handle: filesystem` | Real files from `dist/` are served as-is |
| 5 | `/assets/(.*)` | 404 for a missing asset (instead of HTML with status 200) |
| 6 | `/(.*)` | `index.html`: the SPA fallback for `/rewrites/:id`, `/resumes/:id`, `/matches/:id`, `/jobs/:id`, `/reviews/:id`, `/account`, … |

API responses are `Cache-Control: no-store` by default (set by the API), so Vercel's CDN does not cache
per-user data. Exports already sent `no-store`. The API's own `Set-Cookie`, `Content-Disposition` and error
bodies pass through unchanged.

**What is verified, and how.** `vercel.json` validates against Vercel's published schema (CI). A unit test
(`src/deployment/vercelConfig.test.ts`) emulates the route order for API paths, deep links, assets and
headers. The same contract runs for real in the nginx image, with deep links, reloads, JSON 404s for unknown
API paths and asset 404s exercised by the smoke test and by Playwright. **Vercel itself has not been
exercised** (no deployment was authorized), so run §4 on the first preview deployment.

## 4. Verify after deploying

```bash
WEB=https://<your-project>.vercel.app
curl -s $WEB/api/v1/health                                    # {"status":"ok"}  (proxied to Render)
curl -s $WEB/api/v1/health/ready                              # status ok: the access key was injected
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' $WEB/api/v1/nope    # 404 application/json
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' $WEB/rewrites/abc   # 200 text/html (SPA)
curl -s -o /dev/null -w '%{http_code}\n' $WEB/assets/missing.js              # 404
curl -sI $WEB/api/v1/health | grep -i cache-control                         # no-store
```

Then:

1. Run the non-AI part of the smoke test against the preview:
   `python3 -I scripts/smoke_test_stack.py $WEB --no-ai`. It registers and deletes a throwaway
   `smoke-…@example.com` account and makes no AI calls. The full run (without `--no-ai`) would spend Gemini
   credits and expects the fake provider's sample data, so do not use it against a real backend.
2. In a browser: register, open a resume, reload on its URL, upload a PDF, download a PDF/DOCX export.
3. DevTools → Network: every request goes to the Vercel origin; the session cookie is `__Host-ra_session`
   (`Secure; HttpOnly; SameSite=Lax`); no request or response contains `x-backend-access-key`.
4. Long requests: generate a rewrite and confirm it completes. External-rewrite proxy time limits on Vercel
   are **not verified here**; AI calls are bounded at 90 s (`AI_TOTAL_TIMEOUT_SECONDS`). If Vercel cuts
   requests sooner, lower that value on Render.
5. Uploads: a 4–5 MB PDF uploads successfully (request bodies on the proxy path are not verified here).

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/api/...` returns 404 HTML or `DEPLOYMENT_NOT_FOUND`-style errors | `BACKEND_URL` is missing for this environment, or has a trailing `/api`. Redeploy after changing environment variables. |
| Every API call returns 403 `forbidden` (JSON from the API) | `BACKEND_ACCESS_KEY` is missing or differs from Render's. |
| Deep link works but assets 404 after a deploy | An old tab requests hashed files from a previous build. Reload. |
| Sign-in works, changes fail with `origin_not_allowed` | Add this exact origin (custom domain or preview URL) to `CORS_ORIGINS` on Render. |
| Logged out on every request | A `VITE_API_BASE_URL` points the browser at another origin. Remove it. |
