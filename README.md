# Resume Analyzer

A local full-stack app where a user uploads a resume (PDF or Markdown) and a job description, and
gets back an LLM-generated fitment score and recommendations.

See [AGENTS.md](AGENTS.md) for the full architecture and conventions.

## Getting Started

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then add your GEMINI_API_KEY
uvicorn main:app --reload
```

Runs on `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs on `http://localhost:5173`.

With both running, open the frontend and click "Ping Gemini" to confirm the
frontend → backend → Gemini API wiring is working end to end.
