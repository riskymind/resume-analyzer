"""Job matching orchestration: load verified inputs -> semantic signals -> deterministic engine -> persist.

The stored ``inputs`` (as-of date and the exact similarities used) together
with the stored resume, job requirements and matching configuration are
sufficient to reproduce a report exactly (see :func:`reproduce_report`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.ai.base import EmbeddingProvider
from app.core.config import Settings
from app.db.models import JobDescription, JobMatch, Resume
from app.repositories import jobs as jobs_repo
from app.repositories import matches as matches_repo
from app.schemas.matching import MatchReport, SemanticSignals
from app.schemas.resume import StructuredResume
from app.services.matching.config import DEFAULT_MATCHING_CONFIG, MatchingConfig
from app.services.matching.engine import match_resume_to_job
from app.services.matching.semantic import compute_signals

logger = logging.getLogger(__name__)


def run_match(
    db: Session,
    *,
    user_id: str,
    resume: Resume,
    job: JobDescription,
    embedder: EmbeddingProvider | None,
    settings: Settings,
    before_remote_call: Callable[[], None] | None = None,
    config: MatchingConfig = DEFAULT_MATCHING_CONFIG,
    as_of: date | None = None,
) -> JobMatch:
    if resume.user_id != user_id or job.user_id != user_id:  # callers load both through scoped queries
        raise PermissionError("Resume and job description must belong to the requesting user.")
    structured_resume = StructuredResume.model_validate(resume.structured)
    structured_job = jobs_repo.to_structured(db, job)
    as_of = as_of or datetime.now(UTC).date()

    signals = compute_signals(
        db,
        embedder,
        enabled=settings.semantic_matching_enabled,
        user_id=user_id,
        resume=structured_resume,
        job=structured_job,
        max_texts=settings.embedding_max_texts,
        before_remote_call=before_remote_call,
    )
    report = match_resume_to_job(
        structured_resume, resume.extracted_text, structured_job, signals, as_of=as_of, config=config
    )
    matches_repo.ensure_config(db, config)
    match = matches_repo.create_match(
        db,
        user_id=user_id,
        resume_id=resume.id,
        job_id=job.id,
        report=report,
        inputs={"as_of": as_of.isoformat(), "semantic": signals.as_inputs()},
    )
    logger.info(
        "job_match_created",
        extra={
            "match_id": match.id,
            "match_score": report.match_score,
            "semantic_status": signals.status,
            "requirements": len(report.requirements),
        },
    )
    return match


def reproduce_report(
    db: Session, match: JobMatch, resume: Resume, job: JobDescription, config: MatchingConfig = DEFAULT_MATCHING_CONFIG
) -> MatchReport:
    """Recompute a stored match from its stored inputs (no AI calls)."""

    if config.version != match.matching_version:
        raise ValueError(f"Match was produced by {match.matching_version}, not {config.version}.")
    return match_resume_to_job(
        StructuredResume.model_validate(resume.structured),
        resume.extracted_text,
        jobs_repo.to_structured(db, job),
        SemanticSignals.model_validate(match.inputs["semantic"]),
        as_of=date.fromisoformat(match.inputs["as_of"]),
        config=config,
    )
