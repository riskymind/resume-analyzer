"""Persistence for job match reports and matching configurations. Scoped to ``user_id`` in SQL."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.db.models import Analysis, JobDescription, JobMatch, MatchingConfigRecord, Resume
from app.db.types import utcnow
from app.schemas.matching import MatchReport
from app.services.matching.config import MatchingConfig


def ensure_config(db: Session, config: MatchingConfig) -> None:
    """Record the configuration snapshot for ``config.version`` (first writer wins; versions are immutable)."""

    dialect = db.get_bind().dialect.name
    insert: Any = postgresql.insert if dialect == "postgresql" else sqlite.insert
    db.execute(
        insert(MatchingConfigRecord.__table__)
        .values(version=config.version, config=config.as_dict(), created_at=utcnow())
        .on_conflict_do_nothing(index_elements=["version"])
    )


def get_config(db: Session, version: str) -> MatchingConfigRecord | None:
    return db.get(MatchingConfigRecord, version)


def create_match(
    db: Session,
    *,
    user_id: str,
    resume_id: str,
    job_id: str,
    report: MatchReport,
    inputs: dict[str, Any],
) -> JobMatch:
    match = JobMatch(
        user_id=user_id,
        resume_id=resume_id,
        job_description_id=job_id,
        matching_version=report.matching_version,
        match_score=report.match_score,
        label=report.label,
        semantic_status=report.semantic.status,
        report=report.model_dump(mode="json"),
        inputs=inputs,
    )
    db.add(match)
    db.flush()
    return match


def get_match(db: Session, *, user_id: str, match_id: str) -> JobMatch | None:
    return db.scalar(select(JobMatch).where(JobMatch.id == match_id, JobMatch.user_id == user_id))


def list_matches(
    db: Session, *, user_id: str, job_id: str | None = None, resume_id: str | None = None
) -> list[tuple[JobMatch, str, str | None]]:
    """Matches (newest first) with the resume filename and job title."""

    statement = (
        select(JobMatch, Resume.filename, JobDescription.title)
        .join(Resume, Resume.id == JobMatch.resume_id)
        .join(JobDescription, JobDescription.id == JobMatch.job_description_id)
        .where(JobMatch.user_id == user_id, Resume.user_id == user_id, JobDescription.user_id == user_id)
        .order_by(JobMatch.created_at.desc(), JobMatch.id)
    )
    if job_id is not None:
        statement = statement.where(JobMatch.job_description_id == job_id)
    if resume_id is not None:
        statement = statement.where(JobMatch.resume_id == resume_id)
    return [(match, filename, title) for match, filename, title in db.execute(statement).all()]


def delete_match(db: Session, *, user_id: str, match_id: str) -> bool:
    match = get_match(db, user_id=user_id, match_id=match_id)
    if match is None:
        return False
    db.execute(delete(Analysis).where(Analysis.job_match_id == match_id, Analysis.user_id == user_id))
    db.delete(match)
    db.flush()
    return True
