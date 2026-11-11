"""Run the API locally with the test suite's fake AI provider, for browser checks without AI credits.

    cd backend
    python -m scripts.mock_ai_server --data-dir /tmp/ra-mock      # then: cd ../frontend && npm run dev

The fake provider returns canned extractions and rewrites for the sample resume and job description in
``tests/fixtures/documents.py`` (upload that resume as ``.md`` and paste that job). Other documents still go
through the real verification, which discards whatever they do not contain, exactly as with a real model.

Development only: it refuses to start when APP_ENV=production, never reads GEMINI_API_KEY, and stores its
SQLite database in the given directory (a throwaway one by default). ``--database-url`` and ``--host`` exist for
the isolated container check (``compose.fake-ai.yaml``), which points it at a throwaway PostgreSQL database.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import uvicorn

from app.application import create_app
from app.core.config import Settings
from tests.conftest import FakeLLM


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="API with a fake AI provider (development only).")
    parser.add_argument("--data-dir", type=Path, default=None, help="directory for the SQLite database")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1", help="bind address (0.0.0.0 inside a container)")
    parser.add_argument(
        "--database-url", default=None, help="use this database instead of SQLite in --data-dir (throwaway data only)"
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        help="extra trusted browser origin, e.g. http://127.0.0.1:5174 (repeatable; used by the Playwright run)",
    )
    args = parser.parse_args(argv)
    if os.environ.get("APP_ENV", "").lower() == "production":
        print("Refusing to run the fake AI provider with APP_ENV=production.", file=sys.stderr)
        return 2
    if args.database_url:
        database_url = args.database_url
        location = "the given database"
    else:
        data_dir: Path = args.data_dir or Path(tempfile.mkdtemp(prefix="ra-mock-"))
        data_dir.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{(data_dir / 'mock.db').as_posix()}"
        location = str(data_dir)
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url=database_url,
        gemini_api_key=None,
        auto_migrate=True,
        log_format="text",
        cors_origins=["http://localhost:5173", "http://127.0.0.1:5173", *args.allow_origin],
    )
    print(f"Mock AI server (FAKE AI provider): database in {location}", file=sys.stderr)
    # workers=1: an in-process app object cannot be forked into workers (and WEB_CONCURRENCY may be set).
    app = create_app(settings, ai_provider=FakeLLM())
    uvicorn.run(app, host=args.host, port=args.port, workers=1, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
