"""Deterministic job matching: create, list, retrieve and delete match reports."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.ai.base import EmbeddingProvider
from app.api.deps import (
    CurrentUser,
    get_current_user,
    get_embedding_provider,
    get_rate_limiter,
    get_session,
    get_settings_dep,
    require_csrf,
)
from app.api.limits import enforce_ai_limits
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.db.models import JobMatch
from app.repositories import jobs as jobs_repo
from app.repositories import matches as matches_repo
from app.repositories import resumes as resumes_repo
from app.schemas.job_api import MatchCreate, MatchDetail, MatchSummary
from app.schemas.matching import MatchReport
from app.services.matches import run_match
from app.services.rate_limit import RateLimiter

router = APIRouter(prefix="/matches", tags=["matches"])


def _summary(match: JobMatch, resume_filename: str, job_title: str | None) -> MatchSummary:
    return MatchSummary(
        id=match.id,
        resume_id=match.resume_id,
        job_id=match.job_description_id,
        resume_filename=resume_filename,
        job_title=job_title,
        match_score=match.match_score,
        label=match.label,
        semantic_status=match.semantic_status,
        matching_version=match.matching_version,
        created_at=match.created_at,
    )


def _detail(match: JobMatch, resume_filename: str, job_title: str | None) -> MatchDetail:
    return MatchDetail(
        **_summary(match, resume_filename, job_title).model_dump(), report=MatchReport.model_validate(match.report)
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MatchDetail)
def create_match(
    body: MatchCreate,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    embedder: Annotated[EmbeddingProvider | None, Depends(get_embedding_provider)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> MatchDetail:
    user_id = current.user.id
    resume = resumes_repo.get_resume(db, user_id=user_id, resume_id=body.resume_id)
    if resume is None:
        raise NotFoundError("Resume not found.")
    job = jobs_repo.get_job(db, user_id=user_id, job_id=body.job_id)
    if job is None:
        raise NotFoundError("Job description not found.")
    # Counted against the AI quota only when uncached embeddings must be fetched.
    match = run_match(
        db,
        user_id=user_id,
        resume=resume,
        job=job,
        embedder=embedder,
        settings=settings,
        before_remote_call=lambda: enforce_ai_limits(limiter, settings, user_id),
    )
    db.commit()
    return _detail(match, resume.filename, job.title)


@router.get("", response_model=list[MatchSummary])
def list_matches(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
    job_id: Annotated[str | None, Query(max_length=36)] = None,
    resume_id: Annotated[str | None, Query(max_length=36)] = None,
) -> list[MatchSummary]:
    rows = matches_repo.list_matches(db, user_id=current.user.id, job_id=job_id, resume_id=resume_id)
    return [_summary(*row) for row in rows]


@router.get("/{match_id}", response_model=MatchDetail)
def get_match(
    match_id: str,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
) -> MatchDetail:
    match = matches_repo.get_match(db, user_id=current.user.id, match_id=match_id)
    if match is None:
        raise NotFoundError("Match report not found.")
    resume = resumes_repo.get_resume(db, user_id=current.user.id, resume_id=match.resume_id)
    job = jobs_repo.get_job(db, user_id=current.user.id, job_id=match.job_description_id)
    if resume is None or job is None:  # pragma: no cover - rows cascade together
        raise NotFoundError("Match report not found.")
    return _detail(match, resume.filename, job.title)


@router.delete("/{match_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_match(
    match_id: str,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
) -> Response:
    if not matches_repo.delete_match(db, user_id=current.user.id, match_id=match_id):
        raise NotFoundError("Match report not found.")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
