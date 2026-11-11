"""Persistence for fit analyses.

Every read and write takes the owning ``user_id`` and filters on it in SQL;
there is deliberately no unscoped accessor for request handlers to misuse.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Analysis
from app.schemas.legacy import AnalysisResult


def create(
    session: Session,
    *,
    user_id: str,
    resume_id: str | None = None,
    job_match_id: str | None = None,
    resume_filename: str,
    jd_source: str,
    resume_text: str,
    jd_text: str,
    result: AnalysisResult,
) -> Analysis:
    analysis = Analysis(
        user_id=user_id,
        resume_id=resume_id,
        job_match_id=job_match_id,
        created_at=datetime.now(UTC).isoformat(),
        resume_filename=resume_filename,
        jd_source=jd_source,
        resume_text=resume_text,
        jd_text=jd_text,
        score=result.score,
        score_label=result.score_label,
        recommendations_json=result.recommendations.model_dump_json(),
    )
    session.add(analysis)
    session.flush()
    return analysis


def list_recent(session: Session, *, user_id: str) -> list[Analysis]:
    statement = (
        select(Analysis).where(Analysis.user_id == user_id).order_by(Analysis.created_at.desc(), Analysis.id.desc())
    )
    return list(session.scalars(statement))


def get(session: Session, *, user_id: str, analysis_id: int) -> Analysis | None:
    return session.scalar(select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user_id))
