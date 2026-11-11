# Frontend

React 18 + Vite 6 single-page app in `frontend/`, written in TypeScript (strict) with a few remaining `.jsx`
components (see [Migration status](#typescript-migration-status)). It talks only to the backend's `/api` routes,
same-origin, with an HttpOnly session cookie and an in-memory CSRF token.

## Structure

| Path | Purpose |
|---|---|
| `src/main.tsx`, `src/App.tsx` | Entry point; the route table (`react-router` 7, declarative mode) |
| `src/auth/` | `AuthProvider` (session state, expiry handling) and `RequireAuth` (protected routes) |
| `src/api/` | Typed API client: `client.ts` (fetch/XHR, error envelope → `ApiError`, CSRF, session-expiry event) and one module per backend area |
| `src/types/api.generated.ts` | **Generated** from the FastAPI OpenAPI schema; never edit by hand |
| `src/types/api.ts` | Friendly names for the generated types; `Wire<T>` marks response fields as present |
| `src/hooks/` | `useResource` (load/retry/not-found per page or panel), `usePageTitle` |
| `src/components/ui/` | Shared primitives: feedback states, page header, tabs, confirmation dialog, score seal |
| `src/components/` | Feature components (reports, pickers, rewrite workspace) |
| `src/pages/` | One component per route |
| `src/test/` | Fake backend (`fakeApi.ts`), typed fixtures, `renderApp` helper |
| `e2e/` | Playwright browser journey against the real API with the fake AI provider |

## Routes

| Path | Page |
|---|---|
| `/login` | Sign in / create account (public). After sign-in the user returns to the page they asked for. |
| `/` | Dashboard: resumes (latest scores + top fixes), recent matches, saved jobs, recent rewrites, quick reviews |
| `/upload` | Drag-and-drop upload with progress → `/resumes/:id` |
| `/resumes`, `/resumes/:id` | Resume list; one resume's quality analysis, its matches and rewrites, delete |
| `/match` | New match (`?resume=` / `?job=` preselect) → `/matches/:id` |
| `/matches`, `/matches/:id` | Saved reports and jobs; one deterministic match report |
| `/jobs/:id` | One job description's verified requirements and its matches |
| `/rewrite` | New AI rewrite (`?resume=` / `?job=` preselect) → `/rewrites/:id` |
| `/rewrites`, `/rewrites/:id` | Saved rewrites; the rewrite workspace |
| `/reviews`, `/reviews/new`, `/reviews/:id` | Quick reviews (the original one-step resume + job flow, `POST /api/analyze`) |
| `/account` | Sign out, delete account |
| anything else | Not-found page |

Every route except `/login` is behind `RequireAuth`. Any API response `401 not_authenticated` fires
`auth:session-expired`; the user is signed out, sent to `/login` with "Your session has ended" and returned to the
same page after signing in. A deliberate sign-out does not remember the page.

A missing or inaccessible resource (the API answers 404 for both, so other users' ids are indistinguishable from
deleted ones) shows "could not be found" with a way back; other errors show the server's message and **Try again**.

**Deployment note (Milestone 8):** deep links such as `/rewrites/abc` need the host to serve `index.html` for
unknown paths (Vercel rewrite / nginx `try_files`). The Vite dev and preview servers already do.

## API types

```bash
cd backend && python -m scripts.export_openapi ../frontend/openapi.json
cd ../frontend && npm run types:generate
```

`openapi.json` and `api.generated.ts` are checked in; CI regenerates them and fails if they differ, so a backend
schema change cannot silently break the frontend. Test fixtures are typed against the same types.

## Commands

```bash
npm run dev            # Vite on :5173, /api proxied to API_PROXY_TARGET (default http://localhost:8000)
npm run typecheck      # tsc for the app (strict) and for tooling/e2e
npm run lint           # ESLint: typescript-eslint, react-hooks, jsx-a11y
npm run format:check   # Prettier (no semicolons, single quotes, 120 columns)
npm test               # Vitest + Testing Library, fake backend at the fetch/XHR boundary
npm run build          # typecheck + production build
npm run check          # all of the above
E2E_PYTHON=../backend/venv/bin/python npm run test:e2e   # Playwright browser journey (see below)
```

## Tests

- **Component/page tests** (`*.test.tsx|jsx`) render the real app with `MemoryRouter` (`renderApp(path)`) against a
  fake backend that records every request. No network, no AI.
- **Browser journey** (`e2e/workflow.spec.ts`): Playwright starts its own API with the **fake AI provider**
  (`backend/scripts/mock_ai_server.py`, refuses `APP_ENV=production`, never reads `GEMINI_API_KEY`) and a throwaway
  SQLite database, plus a Vite server, on dedicated ports (API 8765, web 5174); existing servers are never reused.
  It registers a throwaway account, uploads the synthetic sample resume, matches, rewrites, edits, acknowledges,
  downloads PDF and DOCX, previews all templates, restores a version, deletes the job, checks 390/768 px layouts,
  not-found handling and deletes the account. It fails on any JavaScript error, any 5xx, or any unexpected 4xx.
  It uses the installed Google Chrome (`channel: 'chrome'`); set `E2E_BROWSER_CHANNEL=''` for Playwright's Chromium
  (`npx playwright install chromium` first).
- **CI**: `.github/workflows/frontend.yml` runs the checks and the browser journey. It never deploys.

## Accessibility

- Skip link, one `<h1>` per page, focus moved to the new `<h1>` after user-initiated navigation (not on first load),
  `aria-current` in the main navigation, unique page titles.
- Native elements first: links for navigation, `<dialog>` for confirmations (focus trap, Escape, Cancel focused),
  fieldsets/legends for radio groups, labels for every control, keyboard-reachable file inputs.
- WAI-ARIA tabs (arrow keys, Home/End) where alternatives share one place (paste vs upload; sign in vs register).
- Errors use `role="alert"` and are linked to fields with `aria-describedby`/`aria-invalid`; loading and success use
  `role="status"`; upload progress is a `<progress>` without per-percent announcements.
- Score seals have text alternatives ("Resume quality: 70 out of 100"); colours only mirror the API's labels.
- `prefers-reduced-motion` disables transitions. Every text colour token meets WCAG AA on both background tokens
  (measured: lowest is ochre on paper, 4.88:1; body ink 13.2:1).

## TypeScript migration status

Converted: API layer, types, hooks, auth, layout, all pages, and most components. Still `.jsx` (bundled and tested,
not type-checked; `allowJs`, `checkJs: false`): `components/rewrite/RewriteWorkspace`, `Sections`,
`SuggestionCard`, `VerificationPanel`, `ScoreComparison`, and two older test files. They are covered by the rewrite
tests and the browser journey and can be converted without behaviour changes.
