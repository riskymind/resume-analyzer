"""Resume upload, structured extraction and job-independent quality scoring."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
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
from app.db.models import Resume, ResumeAnalysis
from app.repositories import resumes as resumes_repo
from app.schemas.resume import StructuredResume
from app.schemas.resume_api import ResumeDetail, ResumeSummary, SectionOut
from app.schemas.rewrite import ResumeDocument
from app.schemas.scoring import QualityReport
from app.services.rate_limit import RateLimiter
from app.services.resumes import analyse_resume, parse_resume, save_processed_resume
from app.services.rewriting.document import build_document

router = APIRouter(prefix="/resumes", tags=["resumes"])


def _summary(resume: Resume, analysis: ResumeAnalysis | None) -> ResumeSummary:
    return ResumeSummary(
        id=resume.id,
        filename=resume.filename,
        file_format=resume.file_format,
        created_at=resume.created_at,
        overall_score=analysis.overall_score if analysis else None,
        ats_score=analysis.ats_score if analysis else None,
        label=analysis.label if analysis else None,
    )


def _detail(resume: Resume, analysis: ResumeAnalysis | None) -> ResumeDetail:
    return ResumeDetail(
        **_summary(resume, analysis).model_dump(),
        page_count=resume.page_count,
        warnings=list(resume.warnings),
        sections=[SectionOut(**section) for section in resume.sections],
        text=resume.extracted_text,
        structured=StructuredResume.model_validate(resume.structured),
        quality=QualityReport.model_validate(analysis.report) if analysis else None,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ResumeDetail)
def upload_resume(
    file: Annotated[UploadFile, File()],
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> ResumeDetail:
    parsed = parse_resume(filename=file.filename, content_type=file.content_type, stream=file.file, settings=settings)
    ai = require_ai_provider(provider)
    enforce_ai_limits(limiter, settings, current.user.id)
    processed = analyse_resume(parsed, ai)
    resume, analysis = save_processed_resume(db, user_id=current.user.id, processed=processed)
    db.commit()
    return _detail(resume, analysis)


@router.get("", response_model=list[ResumeSummary])
def list_resumes(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
) -> list[ResumeSummary]:
    return [_summary(resume, analysis) for resume, analysis in resumes_repo.list_resumes(db, user_id=current.user.id)]


@router.get("/{resume_id}", response_model=ResumeDetail)
def get_resume(
    resume_id: str,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
) -> ResumeDetail:
    resume = resumes_repo.get_resume(db, user_id=current.user.id, resume_id=resume_id)
    if resume is None:
        raise NotFoundError("Resume not found.")
    return _detail(resume, resumes_repo.latest_analysis(db, user_id=current.user.id, resume_id=resume_id))


@router.get("/{resume_id}/document", response_model=ResumeDocument)
def get_resume_document(
    resume_id: str,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
) -> ResumeDocument:
    """The verified resume as an editable document with stable item ids (the starting point of a rewrite)."""

    resume = resumes_repo.get_resume(db, user_id=current.user.id, resume_id=resume_id)
    if resume is None:
        raise NotFoundError("Resume not found.")
    return build_document(StructuredResume.model_validate(resume.structured), resume.extracted_text)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(
    resume_id: str,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
) -> Response:
    if not resumes_repo.delete_resume(db, user_id=current.user.id, resume_id=resume_id):
        raise NotFoundError("Resume not found.")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
