"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.base import AIProvider, EmbeddingProvider
from app.ai.factory import build_ai_provider
from app.api.routes import auth, health, jobs, legacy, matches, resumes, rewrites
from app.core.config import BACKEND_DIR, DEFAULT_DATABASE_URL, DEFAULT_SQLITE_PATH, Settings, get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import BackendAccessKeyMiddleware, BodySizeLimitMiddleware, RequestContextMiddleware
from app.db.session import Database
from app.services import auth as auth_service
from app.services.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

API_VERSION = "2.0.0-dev"


def _warn_about_legacy_database_location(settings: Settings) -> None:
    """The pre-refactor app kept its SQLite file at the repository root."""

    legacy_path = BACKEND_DIR.parent / "resume_analyzer.db"
    if settings.database_url == DEFAULT_DATABASE_URL and not DEFAULT_SQLITE_PATH.exists() and legacy_path.exists():
        logger.warning(
            "Found a database from the previous version at %s. To keep its history, stop the server and run: mv %s %s",
            legacy_path,
            legacy_path,
            DEFAULT_SQLITE_PATH,
        )


def _purge_expired_state(database: Database, limiter: RateLimiter) -> None:
    """Best-effort housekeeping; failures must not prevent startup."""

    try:
        with database.session() as db, db.begin():
            removed = auth_service.purge_expired_sessions(db)
        limiter.purge_expired()
        logger.info("expired_state_purged", extra={"sessions": removed})
    except Exception as exc:
        logger.warning("expired_state_purge_failed", extra={"error_type": type(exc).__name__})


def create_app(settings: Settings | None = None, *, ai_provider: AIProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    database = Database(settings.database_url, self_heal=not settings.is_production and settings.effective_auto_migrate)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        _warn_about_legacy_database_location(settings)
        if settings.effective_auto_migrate:
            database.migrate()
        _purge_expired_state(database, app.state.rate_limiter)
        logger.info(
            "startup",
            extra={
                "env": settings.app_env,
                "db_backend": "sqlite" if settings.is_sqlite else "postgresql",
                "ai_provider": settings.ai_provider if app.state.ai_provider else "not_configured",
                "backend_access_key": "required" if settings.backend_access_key else "not_configured",
            },
        )
        yield
        database.dispose()
        logger.info("shutdown")

    docs_enabled = not settings.is_production
    app = FastAPI(
        title="Resume Analyzer API",
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.db = database
    app.state.rate_limiter = RateLimiter(database)
    # AI_CALLS_ENABLED=false wins over everything, including an injected provider.
    if not settings.ai_calls_enabled:
        app.state.ai_provider = None
    else:
        app.state.ai_provider = ai_provider if ai_provider is not None else build_ai_provider(settings)
    # The configured provider doubles as the embedding provider when it supports embeddings.
    app.state.embedding_provider = (
        app.state.ai_provider if isinstance(app.state.ai_provider, EmbeddingProvider) else None
    )

    install_exception_handlers(app)

    # Starlette runs the most recently added middleware first (outermost).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    if settings.backend_access_key is not None:
        # Inside the request-id/access-log middleware, so refusals are logged and carry a request id.
        app.add_middleware(BackendAccessKeyMiddleware, access_key=settings.backend_access_key.get_secret_value())
    app.add_middleware(RequestContextMiddleware)

    # Original endpoints keep their paths; /api/v1 is the versioned surface new
    # features are added to.
    app.include_router(health.router, prefix="/api")
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(legacy.router, prefix="/api")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(resumes.router, prefix="/api/v1")
    app.include_router(jobs.router, prefix="/api/v1")
    app.include_router(matches.router, prefix="/api/v1")
    app.include_router(rewrites.router, prefix="/api/v1")

    return app
