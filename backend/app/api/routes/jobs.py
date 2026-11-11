"""Job descriptions: submission (pasted text or PDF/DOCX/Markdown file), verified extraction, history, deletion."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.ai.base import AIProvider
from app.api.deps import (
    CurrentUser,
    get_current_user,
    get_optional_ai_provider,
    get_rate_limiter,
    get_session,
    get_settings_dep,
    require_ai_provider,
    require_csrf,
)
from app.api.limits import enforce_ai_limits
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.db.models import JobDescription
from app.repositories import jobs as jobs_repo
from app.schemas.job_api import JobDetail, JobSummary
from app.services.job_extraction import extract_structured_job
from app.services.jobs import JobUpload, extract_job, read_job_input
from app.services.rate_limit import RateLimiter

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _summary(job: JobDescription, requirement_count: int, match_count: int) -> JobSummary:
    return JobSummary(
        id=job.id,
        title=job.title,
        company=job.company,
        source=job.source,
        source_format=job.source_format,
        created_at=job.created_at,
        requirement_count=requirement_count,
        match_count=match_count,
    )


def _detail(db: Session, job: JobDescription, match_count: int = 0) -> JobDetail:
    structured = jobs_repo.to_structured(db, job)
    return JobDetail(
        **_summary(job, len(structured.requirements), match_count).model_dump(),
        text=job.raw_text,
        info=structured.info,
        requirements=structured.requirements,
        keywords=structured.keywords,
        extraction=structured.extraction,
        warnings=list(job.warnings),
    )


def _load(db: Session, user_id: str, job_id: str) -> JobDescription:
    job = jobs_repo.get_job(db, user_id=user_id, job_id=job_id)
    if job is None:
        raise NotFoundError("Job description not found.")
    return job


@router.post("", status_code=status.HTTP_201_CREATED, response_model=JobDetail)
def submit_job(
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    text: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> JobDetail:
    upload = JobUpload(file.filename, file.content_type, file.file) if file is not None and file.filename else None
    job_input = read_job_input(text=text, upload=upload, settings=settings)
    ai = require_ai_provider(provider)
    enforce_ai_limits(limiter, settings, current.user.id)
    structured = extract_job(ai, job_input)
    job = jobs_repo.create_job(
        db,
        user_id=current.user.id,
        source=job_input.source,
        source_format=job_input.source_format,
        content_sha256=job_input.content_sha256,
        text=job_input.text,
        structured=structured,
    )
    db.commit()
    return _detail(db, job)


@router.get("", response_model=list[JobSummary])
def list_jobs(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
) -> list[JobSummary]:
    return [_summary(*row) for row in jobs_repo.list_jobs(db, user_id=current.user.id)]


@router.get("/{job_id}", response_model=JobDetail)
def get_job(
    job_id: str,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
) -> JobDetail:
    job = _load(db, current.user.id, job_id)
    match_count = next((m for j, _, m in jobs_repo.list_jobs(db, user_id=current.user.id) if j.id == job.id), 0)
    return _detail(db, job, match_count)


@router.post("/{job_id}/extraction", response_model=JobDetail)
def re_extract_job(
    job_id: str,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> JobDetail:
    """Re-run extraction on the stored text (e.g. after an extraction prompt upgrade). Existing reports are kept."""

    job = _load(db, current.user.id, job_id)
    ai = require_ai_provider(provider)
    enforce_ai_limits(limiter, settings, current.user.id)
    jobs_repo.replace_extraction(db, job, extract_structured_job(ai, text=job.raw_text))
    db.commit()
    return _detail(db, job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: str,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
) -> Response:
    if not jobs_repo.delete_job(db, user_id=current.user.id, job_id=job_id):
        raise NotFoundError("Job description not found.")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
