"""Original fit-analysis endpoints, kept with an unchanged contract for the current frontend.

Handlers are plain ``def`` so FastAPI runs them in its thread pool: PDF parsing
and the blocking AI call no longer stall the event loop (and every other
request) as they did when this handler was ``async def``.

All endpoints require a signed-in user, and every query is scoped to that
user in the repository layer. Another user's record is reported as "not
found", so its existence is not revealed.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.ai.base import AIProvider, EmbeddingProvider
from app.api.deps import (
    CurrentUser,
    get_current_user,
    get_embedding_provider,
    get_optional_ai_provider,
    get_rate_limiter,
    get_session,
    get_settings_dep,
    require_ai_provider,
    require_csrf,
)
from app.api.limits import enforce_ai_limits
from app.core.config import Settings
from app.core.errors import AppError, InvalidFileError, NotFoundError
from app.db.models import Analysis
from app.repositories import analyses as analyses_repo
from app.repositories import jobs as jobs_repo
from app.repositories import resumes as resumes_repo
from app.schemas.legacy import AnalysisListItem, AnalysisRecord, AnalysisResult, Recommendations
from app.schemas.matching import MatchReport
from app.schemas.scoring import QualityReport
from app.services.fit_analysis import legacy_result
from app.services.jobs import JobUpload, extract_job, read_job_input
from app.services.matches import run_match
from app.services.rate_limit import RateLimiter
from app.services.resumes import analyse_resume, parse_resume, save_processed_resume

router = APIRouter(tags=["fit-analysis (legacy)"])


def _quality(session: Session, row: Analysis) -> QualityReport | None:
    if row.resume_id is None or row.user_id is None:
        return None  # created before structured resumes existed
    analysis = resumes_repo.latest_analysis(session, user_id=row.user_id, resume_id=row.resume_id)
    return QualityReport.model_validate(analysis.report) if analysis else None


def _to_record(row: Analysis, quality: QualityReport | None = None) -> AnalysisRecord:
    return AnalysisRecord(
        id=row.id,
        created_at=row.created_at,
        resume_filename=row.resume_filename,
        jd_source=row.jd_source,
        resume_id=row.resume_id,
        job_match_id=row.job_match_id,
        resume_quality=quality,
        result=AnalysisResult(
            score=row.score,
            score_label=row.score_label,
            recommendations=Recommendations(**json.loads(row.recommendations_json)),
        ),
    )


@router.post("/analyze", response_model=AnalysisRecord)
def analyze(
    resume: Annotated[UploadFile, File()],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
    embedder: Annotated[EmbeddingProvider | None, Depends(get_embedding_provider)],
    current: Annotated[CurrentUser, Depends(require_csrf)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    jd_text: Annotated[str | None, Form()] = None,
    jd_file: Annotated[UploadFile | None, File()] = None,
) -> AnalysisRecord:
    jd_text_provided = bool(jd_text and jd_text.strip())
    jd_file_provided = bool(jd_file is not None and jd_file.filename)

    if jd_text_provided == jd_file_provided:
        raise AppError("Provide the job description as either pasted text or a file, not both or neither.")

    try:
        parsed = parse_resume(
            filename=resume.filename, content_type=resume.content_type, stream=resume.file, settings=settings
        )
    except InvalidFileError as exc:
        raise InvalidFileError(f"Resume file error: {exc.message}") from exc

    upload = JobUpload(jd_file.filename, jd_file.content_type, jd_file.file) if jd_file and jd_file_provided else None
    # The original contract accepted any non-empty pasted text, so no minimum length is enforced here.
    job_input = read_job_input(
        text=jd_text if not upload else None, upload=upload, settings=settings, enforce_minimum=False
    )

    ai = require_ai_provider(provider)
    user_id = current.user.id
    enforce_ai_limits(limiter, settings, user_id)
    # Both AI extractions complete before anything is written: a failure in either
    # leaves no partial resume, job or analysis behind.
    processed = analyse_resume(parsed, ai)
    structured_job = extract_job(ai, job_input)

    saved_resume, _ = save_processed_resume(session, user_id=user_id, processed=processed)
    job = jobs_repo.create_job(
        session,
        user_id=user_id,
        source=job_input.source,
        source_format=job_input.source_format,
        content_sha256=job_input.content_sha256,
        text=job_input.text,
        structured=structured_job,
    )
    # The score is the deterministic match percentage (the AI quota was already counted above).
    match = run_match(session, user_id=user_id, resume=saved_resume, job=job, embedder=embedder, settings=settings)
    result = legacy_result(MatchReport.model_validate(match.report), processed.report)
    row = analyses_repo.create(
        session,
        user_id=user_id,
        resume_id=saved_resume.id,
        job_match_id=match.id,
        resume_filename=resume.filename or "resume",
        jd_source=job_input.source,
        resume_text=parsed.document.text,
        jd_text=job_input.text,
        result=result,
    )
    session.commit()
    return _to_record(row, processed.report)


@router.get("/analyses", response_model=list[AnalysisListItem])
def list_analyses(
    session: Annotated[Session, Depends(get_session)],
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[AnalysisListItem]:
    return [
        AnalysisListItem(
            id=row.id,
            created_at=row.created_at,
            resume_filename=row.resume_filename,
            score=row.score,
            score_label=row.score_label,
        )
        for row in analyses_repo.list_recent(session, user_id=current.user.id)
    ]


@router.get("/analyses/{analysis_id}", response_model=AnalysisRecord)
def get_analysis(
    analysis_id: int,
    session: Annotated[Session, Depends(get_session)],
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> AnalysisRecord:
    row = analyses_repo.get(session, user_id=current.user.id, analysis_id=analysis_id)
    if row is None:
        raise NotFoundError(f"Analysis {analysis_id} not found.")
    return _to_record(row, _quality(session, row))
