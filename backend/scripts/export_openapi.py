"""Write the API's OpenAPI schema to a file, for generating the frontend's TypeScript types.

    cd backend
    python -m scripts.export_openapi ../frontend/openapi.json
    cd ../frontend && npm run types:generate

The schema is produced from the FastAPI app itself, so the frontend types follow the backend's Pydantic
models instead of a hand-maintained copy. No database, network or AI provider is touched: the app is built
with a throwaway in-memory SQLite URL and no API key, and its lifespan (migrations, startup) never runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.application import create_app
from app.core.config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the OpenAPI schema as JSON.")
    parser.add_argument("output", type=Path, help="file to write, e.g. ../frontend/openapi.json")
    args = parser.parse_args(argv)
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="sqlite:///:memory:",
        gemini_api_key=None,
        auto_migrate=False,
        log_format="text",
    )
    schema = create_app(settings).openapi()
    args.output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
