# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This repository is pre-scaffold: no `backend/` or `frontend/` code exists yet. The only substantive
file is [AGENTS.md](AGENTS.md), which defines the standing technical conventions for the project
described below. Treat AGENTS.md as the source of truth for architecture and conventions — this file
summarizes it; if the two ever diverge (e.g. after scaffolding changes the structure), AGENTS.md wins
and this file should be updated to match.

Feature-level requirements (exact UI fields, scoring rubric, recommendation format, etc.) live in Jira,
not in this repo — don't assume or hardcode them.

## What the app does

A local full-stack app where a user uploads a resume (PDF or Markdown) and a job description (pasted
text or file). The backend sends both to an LLM and returns a fitment score plus recommendations
(missing keywords, phrasing improvements, skill gaps, formatting notes). Every analysis run is persisted
to a local SQLite database, including the raw extracted text and the LLM's structured output, so past
results can be viewed again without re-calling the LLM.

## Planned architecture

- **Backend**: Python 3.11+, FastAPI. Entry point `backend/main.py` (app, CORS, router mounting).
  `backend/database.py` owns the SQLite connection and schema init (no external migration tool).
  `backend/models.py` holds Pydantic schemas — routes pass Pydantic models across boundaries, never raw
  dicts. Routes live in `backend/routes/` (e.g. `resume.py` for upload/analyze/history endpoints) and
  stay thin: LLM prompt construction belongs in `backend/services/gemini_client.py`, not inline in
  handlers. `backend/services/file_parser.py` extracts raw text from PDF/MD uploads.
- **Frontend**: React + Vite under `frontend/`. Functional components with hooks only. API calls live in
  `frontend/src/api/`, not scattered in components. Component files are PascalCase, utilities camelCase.
- **LLM**: Gemini API via the `google-generativeai` SDK, called only from `gemini_client.py`.
- **Database**: single SQLite file (`resume_analyzer.db`, gitignored, created at runtime). Tables are
  lowercase/plural; every table has `id` and a UTC `created_at`.

## Conventions to follow when adding code

- All backend endpoints live under `/api/...` and return JSON.
- Wrap LLM calls in try/except; on failure return a `502`-style error rather than a silent fallback.
- Load secrets (`GEMINI_API_KEY`) via `.env` + `python-dotenv` — never hardcode or commit them.
  `backend/.env.example` documents the expected variable.
- Validate uploaded files for type (`.pdf`, `.md`) and size before parsing.
- Branch naming: `feature/<short-description>` (Jira ticket number optional, e.g.
  `feature/jira-123-upload-flow`). One logical change per PR.

## Local development (once scaffolded)

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

Backend runs on `http://localhost:8000`, frontend on `http://localhost:5173` (Vite default); CORS in
`main.py` is configured for that pairing. A `.env` file with a valid `GEMINI_API_KEY` is required in
`backend/` before any analysis endpoint will work.
