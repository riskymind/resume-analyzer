"""Accounts and server-side sessions.

Every function takes the request's SQLAlchemy session and leaves committing to
the caller, so each HTTP request is one transaction.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, AuthenticationError, ConflictError
from app.core.security import (
    burn_password_check,
    hash_password,
    hash_token,
    needs_rehash,
    new_csrf_token,
    new_session_token,
    verify_password,
)
from app.db.models import (
    Analysis,
    AuthSession,
    EmbeddingCacheEntry,
    JobDescription,
    JobMatch,
    JobRequirementRecord,
    Resume,
    ResumeAnalysis,
    ResumeRewrite,
    RewriteExport,
    RewriteVersion,
    User,
)
from app.db.types import utcnow

logger = logging.getLogger(__name__)

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 1024
_EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
# Writing last_seen_at on every request would turn reads into writes.
_LAST_SEEN_RESOLUTION = timedelta(minutes=5)


def _now() -> datetime:
    return utcnow()


def _rowcount(result: Any) -> int:
    return int(cast(CursorResult[Any], result).rowcount or 0)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def validate_new_credentials(email: str, password: str) -> str:
    normalised = normalise_email(email)
    if len(normalised) > 320 or not _EMAIL_PATTERN.match(normalised):
        raise AppError("Enter a valid email address.", code="invalid_email")
    if len(password) < PASSWORD_MIN_LENGTH:
        raise AppError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.", code="weak_password")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise AppError("Password is too long.", code="weak_password")
    if password.strip().lower() == normalised:
        raise AppError("Password must not be the same as your email address.", code="weak_password")
    return normalised


@dataclass(frozen=True)
class IssuedSession:
    token: str
    session: AuthSession


@dataclass(frozen=True)
class DeletionSummary:
    analyses: int
    sessions: int


def register(db: Session, settings: Settings, *, email: str, password: str) -> User:
    normalised = validate_new_credentials(email, password)
    if db.scalar(select(User.id).where(User.email == normalised)) is not None:
        raise ConflictError("An account with this email already exists.")
    user = User(email=normalised, password_hash=hash_password(settings, password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent registration with the same email
        raise ConflictError("An account with this email already exists.") from exc
    logger.info("user_registered", extra={"user_id": user.id})
    return user


def authenticate(db: Session, settings: Settings, *, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == normalise_email(email)))
    if user is None:
        burn_password_check(settings, password)
        raise AuthenticationError("Invalid email or password.", code="invalid_credentials")
    if not verify_password(settings, user.password_hash, password):
        logger.info("login_failed", extra={"user_id": user.id})
        raise AuthenticationError("Invalid email or password.", code="invalid_credentials")
    if needs_rehash(settings, user.password_hash):
        user.password_hash = hash_password(settings, password)
    return user


def issue_session(db: Session, settings: Settings, user: User, *, replacing_token: str | None) -> IssuedSession:
    """Create a fresh session after successful authentication.

    Any session identified by the cookie the client presented is revoked
    first, so a session id can never survive a login (session fixation).
    """

    now = _now()
    if replacing_token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(replacing_token)))
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at <= now))

    token = new_session_token()
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=new_csrf_token(),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(auth_session)
    db.flush()
    logger.info("session_created", extra={"user_id": user.id, "session_id": auth_session.id})
    return IssuedSession(token=token, session=auth_session)


def resolve_session(db: Session, settings: Settings, token: str | None) -> tuple[AuthSession, User] | None:
    if not token:
        return None
    auth_session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if auth_session is None:
        return None

    now = _now()
    idle_deadline = auth_session.last_seen_at + timedelta(hours=settings.session_idle_timeout_hours)
    if auth_session.expires_at <= now or idle_deadline <= now:
        db.delete(auth_session)
        db.flush()
        return None

    user = db.get(User, auth_session.user_id)
    if user is None:
        return None
    if now - auth_session.last_seen_at >= _LAST_SEEN_RESOLUTION:
        auth_session.last_seen_at = now
    return auth_session, user


def revoke_session(db: Session, auth_session: AuthSession) -> None:
    db.delete(auth_session)
    db.flush()
    logger.info("session_revoked", extra={"user_id": auth_session.user_id, "session_id": auth_session.id})


def delete_account(db: Session, settings: Settings, user: User, *, password: str) -> DeletionSummary:
    """Delete the user and everything they own, inside the caller's transaction.

    Rows are deleted explicitly (not only via ON DELETE CASCADE) so cleanup
    does not depend on foreign-key enforcement being enabled on the backend.
    """

    if not verify_password(settings, user.password_hash, password):
        raise AppError("Password is incorrect.", code="password_incorrect", status_code=403)

    analyses = _rowcount(db.execute(delete(Analysis).where(Analysis.user_id == user.id)))
    _rowcount(db.execute(delete(RewriteExport).where(RewriteExport.user_id == user.id)))
    _rowcount(db.execute(delete(RewriteVersion).where(RewriteVersion.user_id == user.id)))
    _rowcount(db.execute(delete(ResumeRewrite).where(ResumeRewrite.user_id == user.id)))
    _rowcount(db.execute(delete(JobMatch).where(JobMatch.user_id == user.id)))
    _rowcount(db.execute(delete(JobRequirementRecord).where(JobRequirementRecord.user_id == user.id)))
    _rowcount(db.execute(delete(JobDescription).where(JobDescription.user_id == user.id)))
    _rowcount(db.execute(delete(EmbeddingCacheEntry).where(EmbeddingCacheEntry.user_id == user.id)))
    _rowcount(db.execute(delete(ResumeAnalysis).where(ResumeAnalysis.user_id == user.id)))
    resumes = _rowcount(db.execute(delete(Resume).where(Resume.user_id == user.id)))
    sessions = _rowcount(db.execute(delete(AuthSession).where(AuthSession.user_id == user.id)))
    user_id = user.id
    db.delete(user)
    db.flush()

    remaining = [
        db.scalar(select(func.count()).select_from(model).where(model.user_id == user_id))
        for model in (
            Analysis,
            RewriteExport,
            RewriteVersion,
            ResumeRewrite,
            JobMatch,
            JobRequirementRecord,
            JobDescription,
            EmbeddingCacheEntry,
            ResumeAnalysis,
            Resume,
            AuthSession,
        )
    ]
    if any(remaining):
        raise RuntimeError("Account deletion left owned rows behind; transaction rolled back.")

    logger.info(
        "account_deleted", extra={"user_id": user_id, "analyses": analyses, "resumes": resumes, "sessions": sessions}
    )
    return DeletionSummary(analyses=analyses, sessions=sessions)


def purge_expired_sessions(db: Session) -> int:
    return _rowcount(db.execute(delete(AuthSession).where(AuthSession.expires_at <= _now())))
