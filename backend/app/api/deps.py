"""FastAPI dependencies (the dependency-injection seams used by routes and tests)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.ai.base import AIProvider, EmbeddingProvider
from app.core.config import Settings
from app.core.errors import AIUnavailableError, AuthenticationError, CsrfError
from app.core.security import normalise_origin, origin_allowed, tokens_match
from app.db.models import AuthSession, User
from app.db.session import Database
from app.services import auth as auth_service
from app.services.rate_limit import RateLimiter

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_database(request: Request) -> Database:
    database: Database = request.app.state.db
    return database


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def get_session(request: Request) -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any error."""

    session = get_database(request).session()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def get_optional_ai_provider(request: Request) -> AIProvider | None:
    """The configured provider, or ``None``.

    Routes call :func:`require_ai_provider` *after* validating their inputs, so
    a bad upload is reported as such even when AI is not configured.
    """

    provider: AIProvider | None = request.app.state.ai_provider
    return provider


def get_embedding_provider(request: Request) -> EmbeddingProvider | None:
    """The embedding provider for semantic matching, or ``None`` (matching then runs deterministic-only)."""

    provider: EmbeddingProvider | None = getattr(request.app.state, "embedding_provider", None)
    return provider


def require_ai_provider(provider: AIProvider | None) -> AIProvider:
    if provider is None:
        raise AIUnavailableError(
            "AI analysis is not available on this server (GEMINI_API_KEY is not set or AI_CALLS_ENABLED is false)."
        )
    return provider


def client_ip(request: Request) -> str:
    """Client address as resolved by uvicorn's proxy-header handling (see docs/auth.md)."""

    return request.client.host if request.client else "unknown"


def session_token_from(request: Request, settings: Settings) -> str | None:
    return request.cookies.get(settings.session_cookie_name)


def verify_request_origin(request: Request, settings: Settings) -> None:
    """Reject state-changing requests whose Origin/Referer is not a trusted frontend."""

    own_origin = normalise_origin(f"{request.url.scheme}://{request.url.netloc}") or ""
    if not origin_allowed(
        origin_header=request.headers.get("origin"),
        referer_header=request.headers.get("referer"),
        own_origin=own_origin,
        allowed=settings.cors_origins,
    ):
        raise CsrfError("Request origin is not allowed.", code="origin_not_allowed")


@dataclass(frozen=True)
class CurrentUser:
    user: User
    auth_session: AuthSession


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> CurrentUser:
    resolved = auth_service.resolve_session(db, settings, session_token_from(request, settings))
    if resolved is None:
        # Persist the removal of an expired session before the 401 rolls the
        # request transaction back.
        db.commit()
        raise AuthenticationError("Sign in to continue.")
    auth_session, user = resolved
    return CurrentUser(user=user, auth_session=auth_session)


def require_csrf(
    request: Request,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> CurrentUser:
    """Authenticated user for a state-changing request.

    Two independent checks, so protection does not rest on SameSite cookies
    alone: the Origin/Referer must be a trusted frontend origin, and the
    ``X-CSRF-Token`` header must equal the token bound to this session (a
    cross-site page can neither read that token nor set custom headers on a
    simple cross-origin request).
    """

    if request.method in SAFE_METHODS:
        return current
    verify_request_origin(request, settings)
    if not tokens_match(current.auth_session.csrf_token, request.headers.get(CSRF_HEADER)):
        raise CsrfError("Missing or invalid CSRF token. Reload the page and try again.")
    return current
