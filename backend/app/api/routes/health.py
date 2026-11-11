"""Liveness and readiness probes."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import get_database
from app.db.session import Database

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Checks no dependencies (safe for platform health checks)."""

    return {"status": "ok"}


@router.get("/health/ready")
def ready(request: Request, database: Annotated[Database, Depends(get_database)]) -> JSONResponse:
    """Readiness: the database answers and the AI provider is configured."""

    checks: dict[str, str] = {}
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("readiness_db_failed", extra={"error_type": type(exc).__name__})
        checks["database"] = "unavailable"

    if not request.app.state.settings.ai_calls_enabled:
        checks["ai_provider"] = "disabled"  # deliberate operator choice (AI_CALLS_ENABLED=false), not a fault
    else:
        checks["ai_provider"] = "ok" if request.app.state.ai_provider is not None else "not_configured"
    healthy = all(value in ("ok", "disabled") for value in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503, content={"status": "ok" if healthy else "degraded", "checks": checks}
    )
