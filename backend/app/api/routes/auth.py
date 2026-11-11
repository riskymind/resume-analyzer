"""Registration, login, logout, current user, and account deletion."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentUser,
    client_ip,
    get_current_user,
    get_rate_limiter,
    get_session,
    get_settings_dep,
    require_csrf,
    session_token_from,
    verify_request_origin,
)
from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.db.models import AuthSession, User
from app.schemas.auth import AuthResponse, Credentials, DeleteAccountRequest, UserOut
from app.services import auth as auth_service
from app.services.rate_limit import RateLimiter

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

LOGIN_WINDOW_SECONDS = 15 * 60
REGISTER_WINDOW_SECONDS = 60 * 60
_TOO_MANY_LOGINS = "Too many sign-in attempts. Please wait and try again."


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
        secure=settings.effective_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.effective_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _auth_response(user: User, auth_session: AuthSession) -> AuthResponse:
    return AuthResponse(
        user=UserOut(id=user.id, email=user.email, created_at=user.created_at),
        csrf_token=auth_session.csrf_token,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=AuthResponse)
def register(
    body: Credentials,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> AuthResponse:
    verify_request_origin(request, settings)
    limiter.hit(
        "register:ip",
        client_ip(request),
        limit=settings.register_max_per_ip,
        window_seconds=REGISTER_WINDOW_SECONDS,
        message="Too many accounts created from this network. Please try again later.",
    )
    user = auth_service.register(db, settings, email=body.email, password=body.password)
    issued = auth_service.issue_session(db, settings, user, replacing_token=session_token_from(request, settings))
    db.commit()
    _set_session_cookie(response, settings, issued.token)
    return _auth_response(user, issued.session)


@router.post("/login", response_model=AuthResponse)
def login(
    body: Credentials,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> AuthResponse:
    verify_request_origin(request, settings)
    # Counted before the password check, in their own transactions, so failed
    # attempts are counted too.
    limiter.hit(
        "login:ip",
        client_ip(request),
        limit=settings.login_max_attempts_per_ip,
        window_seconds=LOGIN_WINDOW_SECONDS,
        message=_TOO_MANY_LOGINS,
    )
    limiter.hit(
        "login:email",
        auth_service.normalise_email(body.email),
        limit=settings.login_max_attempts_per_email,
        window_seconds=LOGIN_WINDOW_SECONDS,
        message=_TOO_MANY_LOGINS,
    )
    user = auth_service.authenticate(db, settings, email=body.email, password=body.password)
    issued = auth_service.issue_session(db, settings, user, replacing_token=session_token_from(request, settings))
    db.commit()
    _set_session_cookie(response, settings, issued.token)
    return _auth_response(user, issued.session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    try:
        current = get_current_user(request, db, settings)
    except AuthenticationError:
        # No valid session: nothing to revoke; just make sure the cookie is gone.
        _clear_session_cookie(response, settings)
        return response
    require_csrf(request, current, settings)
    auth_service.revoke_session(db, current.auth_session)
    db.commit()
    _clear_session_cookie(response, settings)
    return response


@router.get("/me", response_model=AuthResponse)
def me(current: Annotated[CurrentUser, Depends(get_current_user)]) -> AuthResponse:
    return _auth_response(current.user, current.auth_session)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    body: DeleteAccountRequest,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> Response:
    auth_service.delete_account(db, settings, current.user, password=body.password)
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response, settings)
    return response
