"""Persistence for resumes and their quality reports.

Every query is scoped to the owning ``user_id`` in SQL.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Analysis, JobMatch, Resume, ResumeAnalysis
from app.parsing.files import ExtractedDocument
from app.parsing.sections import DocumentLayout
from app.repositories import rewrites as rewrites_repo
from app.schemas.resume import StructuredResume
from app.schemas.scoring import QualityReport


def create_resume(
    db: Session,
    *,
    user_id: str,
    filename: str,
    document: ExtractedDocument,
    layout: DocumentLayout,
    structured: StructuredResume,
) -> Resume:
    resume = Resume(
        user_id=user_id,
        filename=filename,
        file_format=document.format,
        content_sha256=document.content_sha256,
        page_count=document.page_count,
        extracted_text=document.text,
        sections=[{"kind": s.kind, "heading": s.heading} for s in layout.sections],
        structured=structured.model_dump(mode="json"),
        warnings=list(structured.extraction.warnings),
    )
    db.add(resume)
    db.flush()
    return resume


def create_analysis(db: Session, *, user_id: str, resume_id: str, report: QualityReport) -> ResumeAnalysis:
    analysis = ResumeAnalysis(
        resume_id=resume_id,
        user_id=user_id,
        scoring_version=report.scoring_version,
        overall_score=report.overall_score,
        ats_score=report.ats_score,
        label=report.label,
        report=report.model_dump(mode="json"),
    )
    db.add(analysis)
    db.flush()
    return analysis


def list_resumes(db: Session, *, user_id: str) -> list[tuple[Resume, ResumeAnalysis | None]]:
    resumes = list(
        db.scalars(select(Resume).where(Resume.user_id == user_id).order_by(Resume.created_at.desc(), Resume.id))
    )
    latest = _latest_analyses(db, user_id=user_id, resume_ids=[r.id for r in resumes])
    return [(resume, latest.get(resume.id)) for resume in resumes]


def get_resume(db: Session, *, user_id: str, resume_id: str) -> Resume | None:
    return db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))


def latest_analysis(db: Session, *, user_id: str, resume_id: str) -> ResumeAnalysis | None:
    return _latest_analyses(db, user_id=user_id, resume_ids=[resume_id]).get(resume_id)


def _latest_analyses(db: Session, *, user_id: str, resume_ids: list[str]) -> dict[str, ResumeAnalysis]:
    if not resume_ids:
        return {}
    rows = db.scalars(
        select(ResumeAnalysis)
        .where(ResumeAnalysis.user_id == user_id, ResumeAnalysis.resume_id.in_(resume_ids))
        .order_by(ResumeAnalysis.created_at.asc(), ResumeAnalysis.id)
    )
    return {row.resume_id: row for row in rows}  # later rows overwrite earlier ones


def delete_resume(db: Session, *, user_id: str, resume_id: str) -> bool:
    """Delete a resume, its quality reports, job match reports, rewrites and fit analyses that embed its text."""

    resume = get_resume(db, user_id=user_id, resume_id=resume_id)
    if resume is None:
        return False
    db.execute(delete(Analysis).where(Analysis.resume_id == resume_id, Analysis.user_id == user_id))
    rewrites_repo.delete_for_resume(db, user_id=user_id, resume_id=resume_id)
    db.execute(delete(JobMatch).where(JobMatch.resume_id == resume_id, JobMatch.user_id == user_id))
    db.execute(delete(ResumeAnalysis).where(ResumeAnalysis.resume_id == resume_id, ResumeAnalysis.user_id == user_id))
    db.delete(resume)
    db.flush()
    return True
