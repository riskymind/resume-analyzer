"""Persistence for rewrite sessions, versions and export metadata. Every query is scoped to ``user_id`` in SQL."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from app.db.models import JobDescription, Resume, ResumeRewrite, RewriteExport, RewriteVersion
from app.db.types import utcnow


def create_rewrite(
    db: Session,
    *,
    user_id: str,
    resume_id: str,
    job_id: str | None,
    name: str,
    mode: str,
    template: str,
    original: dict[str, Any],
) -> ResumeRewrite:
    rewrite = ResumeRewrite(
        user_id=user_id,
        resume_id=resume_id,
        job_description_id=job_id,
        name=name,
        mode=mode,
        template=template,
        current_version=0,
        original=original,
    )
    db.add(rewrite)
    db.flush()
    return rewrite


def get_rewrite(db: Session, *, user_id: str, rewrite_id: str) -> ResumeRewrite | None:
    return db.scalar(select(ResumeRewrite).where(ResumeRewrite.id == rewrite_id, ResumeRewrite.user_id == user_id))


def get_version(db: Session, *, user_id: str, rewrite_id: str, number: int) -> RewriteVersion | None:
    return db.scalar(
        select(RewriteVersion).where(
            RewriteVersion.rewrite_id == rewrite_id,
            RewriteVersion.user_id == user_id,
            RewriteVersion.number == number,
        )
    )


def list_versions(db: Session, *, user_id: str, rewrite_id: str) -> list[Any]:
    """Version metadata, newest first. The large JSON columns are not loaded."""

    return list(
        db.execute(
            select(
                RewriteVersion.number,
                RewriteVersion.source,
                RewriteVersion.created_at,
                RewriteVersion.quality_after,
                RewriteVersion.match_after,
                RewriteVersion.verification_status,
            )
            .where(RewriteVersion.rewrite_id == rewrite_id, RewriteVersion.user_id == user_id)
            .order_by(RewriteVersion.number.desc())
        ).all()
    )


def add_version(db: Session, *, rewrite: ResumeRewrite, values: dict[str, Any]) -> RewriteVersion:
    """Append version ``current_version + 1``. A concurrent writer makes the flush fail on the unique constraint."""

    version = RewriteVersion(
        rewrite_id=rewrite.id, user_id=rewrite.user_id, number=rewrite.current_version + 1, **values
    )
    db.add(version)
    rewrite.current_version = version.number
    db.flush()
    return version


def prune_versions(db: Session, *, rewrite: ResumeRewrite, keep: int) -> int:
    """Keep version 1 (the first generation) and the newest ``keep - 1`` versions."""

    cutoff = rewrite.current_version - keep + 2  # versions >= cutoff are the newest keep - 1
    if cutoff <= 2:
        return 0
    result = db.execute(
        delete(RewriteVersion).where(
            RewriteVersion.rewrite_id == rewrite.id,
            RewriteVersion.user_id == rewrite.user_id,
            RewriteVersion.number > 1,
            RewriteVersion.number < cutoff,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


def list_rewrites(
    db: Session, *, user_id: str, resume_id: str | None = None
) -> list[tuple[ResumeRewrite, RewriteVersion | None, str, str | None]]:
    """Rewrites (most recently updated first) with their current version, resume filename and job title."""

    statement = (
        select(ResumeRewrite, RewriteVersion, Resume.filename, JobDescription.title)
        .join(Resume, and_(Resume.id == ResumeRewrite.resume_id, Resume.user_id == user_id))
        .outerjoin(
            RewriteVersion,
            and_(
                RewriteVersion.rewrite_id == ResumeRewrite.id,
                RewriteVersion.number == ResumeRewrite.current_version,
                RewriteVersion.user_id == user_id,
            ),
        )
        .outerjoin(
            JobDescription,
            and_(JobDescription.id == ResumeRewrite.job_description_id, JobDescription.user_id == user_id),
        )
        .where(ResumeRewrite.user_id == user_id)
        .order_by(ResumeRewrite.updated_at.desc(), ResumeRewrite.id)
    )
    if resume_id is not None:
        statement = statement.where(ResumeRewrite.resume_id == resume_id)
    return [(rewrite, version, filename, title) for rewrite, version, filename, title in db.execute(statement).all()]


def record_export(
    db: Session,
    *,
    rewrite: ResumeRewrite,
    version_number: int,
    fmt: str,
    template: str,
    size_bytes: int,
    verification_status: str | None = None,
    acknowledged_unverified: bool = False,
) -> RewriteExport:
    export = RewriteExport(
        user_id=rewrite.user_id,
        rewrite_id=rewrite.id,
        version_number=version_number,
        format=fmt,
        template=template,
        size_bytes=size_bytes,
        verification_status=verification_status,
        acknowledged_unverified=acknowledged_unverified,
    )
    db.add(export)
    db.flush()
    return export


def count_exports(db: Session, *, user_id: str, rewrite_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(RewriteExport)
            .where(RewriteExport.user_id == user_id, RewriteExport.rewrite_id == rewrite_id)
        )
        or 0
    )


def delete_rewrite(db: Session, *, user_id: str, rewrite_id: str) -> bool:
    rewrite = get_rewrite(db, user_id=user_id, rewrite_id=rewrite_id)
    if rewrite is None:
        return False
    _delete_children(db, user_id=user_id, rewrite_ids=[rewrite_id])
    db.delete(rewrite)
    db.flush()
    return True


def _delete_children(db: Session, *, user_id: str, rewrite_ids: list[str]) -> None:
    if not rewrite_ids:
        return
    db.execute(delete(RewriteExport).where(RewriteExport.rewrite_id.in_(rewrite_ids), RewriteExport.user_id == user_id))
    db.execute(
        delete(RewriteVersion).where(RewriteVersion.rewrite_id.in_(rewrite_ids), RewriteVersion.user_id == user_id)
    )


def delete_for_resume(db: Session, *, user_id: str, resume_id: str) -> int:
    """Delete every rewrite of a resume (explicitly, so cleanup does not rely on FK cascades)."""

    ids = list(
        db.scalars(
            select(ResumeRewrite.id).where(ResumeRewrite.resume_id == resume_id, ResumeRewrite.user_id == user_id)
        )
    )
    _delete_children(db, user_id=user_id, rewrite_ids=ids)
    if ids:
        db.execute(delete(ResumeRewrite).where(ResumeRewrite.id.in_(ids), ResumeRewrite.user_id == user_id))
    return len(ids)


# Verification issue codes whose wording comes from the job description (its employer, title or keywords).
_JOB_ISSUE_CODES = {"target_employer", "target_title", "unsupported_keyword"}
_DETACHED_ISSUE_MESSAGE = (
    "“{term}” was flagged when this rewrite targeted a job that has since been deleted. It is not supported by "
    "your original resume."
)


def _scrub_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Keep the issue and its severity (a claim never becomes verified by deleting the job), drop job wording."""

    if issue.get("code") not in _JOB_ISSUE_CODES:
        return issue
    return {**issue, "message": _DETACHED_ISSUE_MESSAGE.format(term=issue.get("term") or "This wording")}


def _scrub_verification(verification: dict[str, Any]) -> dict[str, Any]:
    return {**verification, "issues": [_scrub_issue(issue) for issue in verification.get("issues", [])]}


def _scrub_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    return {
        **suggestion,
        "keywords": [],
        "requirement_ids": [],
        "rationale": None,  # the model's explanation may describe the deleted job
        "verification": _scrub_verification(suggestion.get("verification", {})),
    }


def detach_job(db: Session, *, user_id: str, job_id: str, job_title: str | None = None) -> int:
    """Keep rewrites of a deleted job, unlink them and remove every job-derived value from all their versions.

    Removed: the match comparison (before/after match scores, newly evidenced and missing requirements), job
    keywords incorporated, gaps, the model's alignment notes, suggestion keywords, requirement ids and
    rationales, and job wording inside verification messages. Kept: the content, the user's decisions, quality
    scores and verification severities. A default name that contains the job title is renamed.
    """

    rewrites = list(
        db.scalars(
            select(ResumeRewrite).where(ResumeRewrite.job_description_id == job_id, ResumeRewrite.user_id == user_id)
        )
    )
    if not rewrites:
        return 0
    detached_at = utcnow()
    ids = [rewrite.id for rewrite in rewrites]
    for rewrite in rewrites:
        rewrite.job_description_id = None
        rewrite.job_detached_at = detached_at
        suffix = f" \u2013 {job_title}" if job_title else None
        if suffix and rewrite.name.endswith(suffix):  # the default name: "<resume> - <job title>"
            rewrite.name = f"{rewrite.name[: -len(suffix)]} \u2013 target job deleted"[:120]
    for version in db.scalars(
        select(RewriteVersion).where(RewriteVersion.rewrite_id.in_(ids), RewriteVersion.user_id == user_id)
    ):
        version.scores = {**version.scores, "match": None, "keywords_incorporated": []}
        version.generation = {**version.generation, "gaps": [], "alignment_notes": []}
        version.suggestions = [_scrub_suggestion(suggestion) for suggestion in version.suggestions]
        version.verification = _scrub_verification(version.verification)
        version.match_after = None
    db.flush()
    return len(ids)


def delete_all_for_user(db: Session, *, user_id: str) -> int:
    db.execute(delete(RewriteExport).where(RewriteExport.user_id == user_id))
    db.execute(delete(RewriteVersion).where(RewriteVersion.user_id == user_id))
    result = db.execute(delete(ResumeRewrite).where(ResumeRewrite.user_id == user_id))
    return int(getattr(result, "rowcount", 0) or 0)
