"""Persistence for job descriptions and their requirements. Every query is scoped to ``user_id`` in SQL."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Analysis, JobDescription, JobMatch, JobRequirementRecord
from app.repositories import rewrites as rewrites_repo
from app.schemas.job import JobRequirement, StructuredJob


def _requirement_rows(user_id: str, job_id: str, structured: StructuredJob) -> list[JobRequirementRecord]:
    return [
        JobRequirementRecord(
            job_description_id=job_id,
            user_id=user_id,
            position=position,
            requirement_key=req.id,
            name=req.name,
            category=req.category,
            classification=req.classification,
            classification_source=req.classification_source,
            importance=req.importance,
            evidence=req.evidence,
            status=req.status,
            min_years=req.min_years,
            alternative_group=req.alternative_group,
        )
        for position, req in enumerate(structured.requirements)
    ]


def _document(structured: StructuredJob) -> dict[str, object]:
    return structured.model_dump(mode="json", exclude={"requirements"})


def create_job(
    db: Session,
    *,
    user_id: str,
    source: str,
    source_format: str,
    content_sha256: str,
    text: str,
    structured: StructuredJob,
) -> JobDescription:
    job = JobDescription(
        user_id=user_id,
        title=structured.info.title.value,
        company=structured.info.company.value,
        source=source,
        source_format=source_format,
        content_sha256=content_sha256,
        raw_text=text,
        structured=_document(structured),
        extraction_version=structured.extraction.prompt_version,
        warnings=list(structured.extraction.warnings),
    )
    db.add(job)
    db.flush()
    db.add_all(_requirement_rows(user_id, job.id, structured))
    db.flush()
    return job


def replace_extraction(db: Session, job: JobDescription, structured: StructuredJob) -> None:
    db.execute(
        delete(JobRequirementRecord).where(
            JobRequirementRecord.job_description_id == job.id, JobRequirementRecord.user_id == job.user_id
        )
    )
    job.title = structured.info.title.value
    job.company = structured.info.company.value
    job.structured = _document(structured)
    job.extraction_version = structured.extraction.prompt_version
    job.warnings = list(structured.extraction.warnings)
    db.add_all(_requirement_rows(job.user_id, job.id, structured))
    db.flush()


def get_job(db: Session, *, user_id: str, job_id: str) -> JobDescription | None:
    return db.scalar(select(JobDescription).where(JobDescription.id == job_id, JobDescription.user_id == user_id))


def requirements_for(db: Session, job: JobDescription) -> list[JobRequirementRecord]:
    return list(
        db.scalars(
            select(JobRequirementRecord)
            .where(JobRequirementRecord.job_description_id == job.id, JobRequirementRecord.user_id == job.user_id)
            .order_by(JobRequirementRecord.position)
        )
    )


def to_structured(db: Session, job: JobDescription) -> StructuredJob:
    requirements = [
        JobRequirement(
            id=row.requirement_key,
            name=row.name,
            category=row.category,
            classification=row.classification,
            classification_source=row.classification_source,
            importance=row.importance,
            evidence=row.evidence,
            status=row.status,
            min_years=row.min_years,
            alternative_group=row.alternative_group,
        )
        for row in requirements_for(db, job)
    ]
    return StructuredJob.model_validate({**job.structured, "requirements": [r.model_dump() for r in requirements]})


def list_jobs(db: Session, *, user_id: str) -> list[tuple[JobDescription, int, int]]:
    """Jobs (newest first) with their requirement and match counts."""

    jobs = list(
        db.scalars(
            select(JobDescription)
            .where(JobDescription.user_id == user_id)
            .order_by(JobDescription.created_at.desc(), JobDescription.id)
        )
    )
    ids = [job.id for job in jobs]
    if not ids:
        return []
    requirement_counts = dict(
        db.execute(
            select(JobRequirementRecord.job_description_id, func.count())
            .where(JobRequirementRecord.user_id == user_id, JobRequirementRecord.job_description_id.in_(ids))
            .group_by(JobRequirementRecord.job_description_id)
        ).all()
    )
    match_counts = dict(
        db.execute(
            select(JobMatch.job_description_id, func.count())
            .where(JobMatch.user_id == user_id, JobMatch.job_description_id.in_(ids))
            .group_by(JobMatch.job_description_id)
        ).all()
    )
    return [(job, int(requirement_counts.get(job.id, 0)), int(match_counts.get(job.id, 0))) for job in jobs]


def delete_job(db: Session, *, user_id: str, job_id: str) -> bool:
    """Delete a job description, its requirements, its match reports and fit analyses produced from them.

    Rewrites targeting the job are kept (they are the user's work) but unlinked, and the job-derived data in
    them (requirement names, gaps, match comparison) is removed.
    """

    job = get_job(db, user_id=user_id, job_id=job_id)
    if job is None:
        return False
    rewrites_repo.detach_job(db, user_id=user_id, job_id=job_id, job_title=job.title)
    match_ids = select(JobMatch.id).where(JobMatch.job_description_id == job_id, JobMatch.user_id == user_id)
    db.execute(delete(Analysis).where(Analysis.job_match_id.in_(match_ids), Analysis.user_id == user_id))
    db.execute(delete(JobMatch).where(JobMatch.job_description_id == job_id, JobMatch.user_id == user_id))
    db.execute(
        delete(JobRequirementRecord).where(
            JobRequirementRecord.job_description_id == job_id, JobRequirementRecord.user_id == user_id
        )
    )
    db.delete(job)
    db.flush()
    return True
