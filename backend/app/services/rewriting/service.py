"""Rewrite workflow: create, regenerate, decide, edit, restore. Routes stay thin; this module owns the rules.

Invariants:

- The source resume is never modified. ``resume_rewrites.original`` is a
  snapshot built from its verified extraction.
- Content = original + applied suggestions + manual edits. A suggestion is
  applied when it is accepted, or pending and verified without warnings.
  Rejected (including auto-rejected) suggestions never reach the content, and a
  suggestion with a blocking verification issue cannot be accepted.
- Every change creates a new immutable version. Verification and both scores
  are recomputed from the saved content each time.
- Accepting, rejecting or regenerating recomposes only the affected *units*
  (summary, one role's bullets, skills, one project, education order,
  certification order); manual edits elsewhere are kept.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import PurePath

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.base import AIProvider
from app.core.config import Settings
from app.core.errors import AppError, ConflictError
from app.db.models import JobDescription, Resume, ResumeRewrite, RewriteVersion
from app.repositories import jobs as jobs_repo
from app.repositories import matches as matches_repo
from app.repositories import resumes as resumes_repo
from app.repositories import rewrites as rewrites_repo
from app.schemas.matching import SemanticSignals
from app.schemas.resume import StructuredResume
from app.schemas.rewrite import (
    SCOPE_SECTIONS,
    DocBullet,
    DocExperience,
    GenerationInfo,
    RegenerateRequest,
    ResumeDocument,
    RewriteCreate,
    RewriteMode,
    RewriteScope,
    RewriteUpdate,
    ScoreComparison,
    Suggestion,
    VerificationSummary,
)
from app.services.matching.engine import match_resume_to_job
from app.services.rewriting.document import build_document
from app.services.rewriting.generator import JobContext, default_mode, generate, sections_for
from app.services.rewriting.scores import compare
from app.services.rewriting.verification import VerificationContext, verify_document

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = "modern"


@dataclass
class RewriteState:
    rewrite: ResumeRewrite
    resume: Resume
    original: ResumeDocument
    structured: StructuredResume
    job: JobContext | None
    vctx: VerificationContext


# --------------------------------------------------------------------------- context


def _job_context(db: Session, job: JobDescription, structured: StructuredResume, text: str, as_of: date) -> JobContext:
    structured_job = jobs_repo.to_structured(db, job)
    report = match_resume_to_job(
        structured,
        text,
        structured_job,
        SemanticSignals(status="disabled", reason="Not used for rewriting."),
        as_of=as_of,
    )
    return JobContext(job_id=job.id, job=structured_job, report=report)


def load_state(db: Session, *, user_id: str, rewrite: ResumeRewrite) -> RewriteState:
    resume = resumes_repo.get_resume(db, user_id=user_id, resume_id=rewrite.resume_id)
    if resume is None:  # pragma: no cover - rewrites are deleted with their resume
        raise AppError("The source resume no longer exists.", code="not_found", status_code=404)
    structured = StructuredResume.model_validate(resume.structured)
    original = ResumeDocument.model_validate(rewrite.original)
    job = None
    if rewrite.job_description_id is not None:
        job_row = jobs_repo.get_job(db, user_id=user_id, job_id=rewrite.job_description_id)
        if job_row is not None:
            job = _job_context(db, job_row, structured, resume.extracted_text, _today())
    vctx = VerificationContext(original=original, resume_text=resume.extracted_text, job=job.job if job else None)
    return RewriteState(rewrite=rewrite, resume=resume, original=original, structured=structured, job=job, vctx=vctx)


def _today() -> date:
    return datetime.now(UTC).date()


# --------------------------------------------------------------------------- composition


def _compose_role(role: DocExperience, suggestions: list[Suggestion]) -> list[DocBullet]:
    """Original bullets in their original order, each replaced by the applied suggestion(s) that rewrite it."""

    position = {bullet.id: index for index, bullet in enumerate(role.bullets)}
    applied = [s for s in suggestions if s.applied and s.source_ids]
    consumed = {source for s in applied for source in s.source_ids}
    anchored: dict[str, list[Suggestion]] = {}
    for suggestion in applied:
        anchor = min(suggestion.source_ids, key=lambda sid: position.get(sid, len(position)))
        anchored.setdefault(anchor, []).append(suggestion)
    bullets: list[DocBullet] = []
    for bullet in role.bullets:
        for suggestion in anchored.get(bullet.id, []):
            bullets.append(
                DocBullet(id=suggestion.id, text=suggestion.proposed, source_ids=list(suggestion.source_ids))
            )
        if bullet.id not in consumed:
            bullets.append(bullet.model_copy(deep=True))
    return bullets


def _reorder(items: list, order: list[str] | None, original_order: list[str]) -> list:  # type: ignore[type-arg]
    sequence = order or original_order
    rank = {item_id: index for index, item_id in enumerate(sequence)}
    return sorted(items, key=lambda item: rank.get(item.id, len(rank)))


def compose(
    content: ResumeDocument, original: ResumeDocument, suggestions: list[Suggestion], units: set[str]
) -> ResumeDocument:
    """Rebuild ``units`` of ``content`` from the original plus the applied suggestions for those units."""

    document = content.model_copy(deep=True)
    for unit in sorted(units):
        mine = [s for s in suggestions if s.unit == unit]
        applied = [s for s in mine if s.applied]
        if unit == "summary":
            document.summary = applied[-1].proposed if applied else original.summary
        elif unit.startswith("experience:"):
            role_id = unit.split(":", 1)[1]
            role = next((r for r in original.experience if r.id == role_id), None)
            target = next((r for r in document.experience if r.id == role_id), None)
            if role is not None and target is not None:
                target.bullets = _compose_role(role, mine)
        elif unit == "skills":
            latest = applied[-1] if applied else None
            document.technical_skills = list(latest.technical or []) if latest else list(original.technical_skills)
            document.soft_skills = list(latest.soft or []) if latest else list(original.soft_skills)
        elif unit.startswith("project:"):
            project_id = unit.split(":", 1)[1]
            base = next((p for p in original.projects if p.id == project_id), None)
            target_project = next((p for p in document.projects if p.id == project_id), None)
            if base is not None and target_project is not None:
                target_project.description = applied[-1].proposed if applied else base.description
        elif unit == "education":
            order = applied[-1].order if applied else None
            document.education = _reorder(document.education, order, [e.id for e in original.education])
        elif unit == "certifications":
            order = applied[-1].order if applied else None
            document.certifications = _reorder(document.certifications, order, [c.id for c in original.certifications])
    return document


# --------------------------------------------------------------------------- versions


@dataclass
class VersionPayload:
    content: ResumeDocument
    suggestions: list[Suggestion]
    generation: GenerationInfo
    verification: VerificationSummary
    scores: ScoreComparison


def evaluate(
    db: Session, state: RewriteState, content: ResumeDocument, suggestions: list[Suggestion]
) -> tuple[VerificationSummary, ScoreComparison]:
    verification = verify_document(content, state.vctx, suggestions)
    uploaded = resumes_repo.latest_analysis(db, user_id=state.rewrite.user_id, resume_id=state.resume.id)
    saved_match = None
    if state.job is not None:
        matches = matches_repo.list_matches(
            db, user_id=state.rewrite.user_id, job_id=state.job.job_id, resume_id=state.resume.id
        )
        saved_match = matches[0][0].match_score if matches else None
    scores = compare(
        original_doc=state.original,
        content=content,
        original_structured=state.structured,
        job=state.job,
        uploaded_score=uploaded.overall_score if uploaded else None,
        saved_match_score=saved_match,
        as_of=_today(),
    )
    return verification, scores


def save_version(
    db: Session,
    state: RewriteState,
    *,
    content: ResumeDocument,
    suggestions: list[Suggestion],
    generation: GenerationInfo,
    source: str,
    settings: Settings,
) -> RewriteVersion:
    verification, scores = evaluate(db, state, content, suggestions)
    try:
        version = rewrites_repo.add_version(
            db,
            rewrite=state.rewrite,
            values={
                "source": source,
                "content": content.model_dump(mode="json"),
                "suggestions": [s.model_dump(mode="json") for s in suggestions],
                "verification": verification.model_dump(mode="json"),
                "scores": scores.model_dump(mode="json"),
                "generation": generation.model_dump(mode="json"),
                "verification_status": verification.status,
                "quality_after": scores.quality.after,
                "match_after": scores.match.after if scores.match else None,
            },
        )
    except IntegrityError as exc:
        raise ConflictError("This rewrite was changed at the same time elsewhere. Reload and try again.") from exc
    state.rewrite.updated_at = version.created_at
    rewrites_repo.prune_versions(db, rewrite=state.rewrite, keep=settings.rewrite_max_versions)
    logger.info(
        "rewrite_version_saved",
        extra={
            "rewrite_id": state.rewrite.id,
            "version": version.number,
            "source": source,
            "verification_status": verification.status,
            "blocking": verification.blocking,
            "quality_after": scores.quality.after,
        },
    )
    return version


def current_version(db: Session, rewrite: ResumeRewrite) -> RewriteVersion:
    version = rewrites_repo.get_version(
        db, user_id=rewrite.user_id, rewrite_id=rewrite.id, number=rewrite.current_version
    )
    if version is None:  # pragma: no cover - a rewrite always has its current version
        raise AppError("Rewrite version not found.", code="not_found", status_code=404)
    return version


def _parse_version(version: RewriteVersion) -> tuple[ResumeDocument, list[Suggestion], GenerationInfo]:
    return (
        ResumeDocument.model_validate(version.content),
        [Suggestion.model_validate(s) for s in version.suggestions],
        GenerationInfo.model_validate(version.generation),
    )


def _check_base(rewrite: ResumeRewrite, base_version: int) -> None:
    if base_version != rewrite.current_version:
        raise ConflictError(
            f"This rewrite has changed since you loaded it (now version {rewrite.current_version}). Reload to see "
            "the latest version before making changes."
        )


# --------------------------------------------------------------------------- scope helpers


def _original_bullet_ids(original: ResumeDocument) -> set[str]:
    return {bullet.id for entry in original.experience for bullet in entry.bullets}


def resolve_bullet_ids(requested: list[str], original: ResumeDocument, content: ResumeDocument | None) -> list[str]:
    """Map requested bullet ids (original ids, or ids of rewritten bullets in the content) to original ids."""

    known = _original_bullet_ids(original)
    current = {b.id: b for entry in (content.experience if content else []) for b in entry.bullets}
    resolved: list[str] = []
    for bullet_id in requested:
        if bullet_id in known:
            sources = [bullet_id]
        elif bullet_id in current:
            sources = [s for s in current[bullet_id].source_ids if s in known]
            if not sources:
                raise AppError("A selected bullet is not from your original resume, so it cannot be regenerated.")
        else:
            raise AppError("A selected bullet does not exist in this resume.", code="unknown_bullet")
        resolved += [s for s in sources if s not in resolved]
    return resolved


def _validate_scope(
    scope: RewriteScope, mode: RewriteMode | None, bullet_ids: list[str], original: ResumeDocument, has_job: bool
) -> None:
    if scope == "keywords" and not has_job:
        raise AppError("Keyword optimisation needs a job description.", code="job_required")
    if mode == "job_targeted" and not has_job:
        raise AppError("A job-targeted rewrite needs a job description.", code="job_required")
    if scope == "bullets" and not bullet_ids:
        raise AppError("Select at least one bullet to rewrite.")
    if not sections_for(scope, original):
        raise AppError("There is nothing to rewrite in the selected scope for this resume.", code="nothing_to_rewrite")


def _default_name(resume: Resume, job: JobContext | None) -> str:
    stem = PurePath(resume.filename).stem or "Resume"
    target = job.title if job and job.title else ("job match" if job else "general improvement")
    return f"{stem} \u2013 {target}"[:120]


ProviderFactory = Callable[[], AIProvider]


# --------------------------------------------------------------------------- operations


def create(
    db: Session,
    *,
    user_id: str,
    resume: Resume,
    job_row: JobDescription | None,
    request: RewriteCreate,
    provider_factory: ProviderFactory,
    settings: Settings,
) -> ResumeRewrite:
    structured = StructuredResume.model_validate(resume.structured)
    original = build_document(structured, resume.extracted_text)
    job = _job_context(db, job_row, structured, resume.extracted_text, _today()) if job_row else None
    unknown = [bullet_id for bullet_id in request.bullet_ids if bullet_id not in _original_bullet_ids(original)]
    if unknown:
        raise AppError("A selected bullet does not exist in this resume.", code="unknown_bullet")
    _validate_scope(request.scope, request.mode, request.bullet_ids, original, job is not None)
    mode = request.mode or default_mode(job)

    provider = provider_factory()  # checks configuration and the AI quota only after validation
    vctx = VerificationContext(original=original, resume_text=resume.extracted_text, job=job.job if job else None)
    generation = generate(
        provider,
        original=original,
        vctx=vctx,
        job=job,
        scope=request.scope,
        mode=mode,
        bullet_ids=request.bullet_ids,
        generation=1,
    )

    rewrite = rewrites_repo.create_rewrite(
        db,
        user_id=user_id,
        resume_id=resume.id,
        job_id=job_row.id if job_row else None,
        name=(request.name or "").strip() or _default_name(resume, job),
        mode=mode,
        template=DEFAULT_TEMPLATE,
        original=original.model_dump(mode="json"),
    )
    state = RewriteState(rewrite=rewrite, resume=resume, original=original, structured=structured, job=job, vctx=vctx)
    content = compose(original, original, generation.suggestions, {s.unit for s in generation.suggestions})
    save_version(
        db,
        state,
        content=content,
        suggestions=generation.suggestions,
        generation=generation.info,
        source="generate",
        settings=settings,
    )
    return rewrite


def regenerate(
    db: Session,
    *,
    user_id: str,
    rewrite: ResumeRewrite,
    request: RegenerateRequest,
    provider_factory: ProviderFactory,
    settings: Settings,
) -> RewriteVersion:
    _check_base(rewrite, request.base_version)
    state = load_state(db, user_id=user_id, rewrite=rewrite)
    content, suggestions, previous = _parse_version(current_version(db, rewrite))
    bullet_ids = resolve_bullet_ids(request.bullet_ids, state.original, content) if request.scope == "bullets" else []
    _validate_scope(request.scope, request.mode, bullet_ids, state.original, state.job is not None)
    mode = request.mode or rewrite.mode
    if mode == "job_targeted" and state.job is None:
        mode = "professional"

    provider = provider_factory()
    number = previous.generation + 1
    generation = generate(
        provider,
        original=state.original,
        vctx=state.vctx,
        job=state.job,
        scope=request.scope,
        mode=mode,  # type: ignore[arg-type]
        bullet_ids=bullet_ids,
        generation=number,
    )

    sections = set(SCOPE_SECTIONS[request.scope])
    selected = set(bullet_ids)

    def replaced(suggestion: Suggestion) -> bool:
        if request.scope == "bullets":
            return suggestion.section == "experience" and bool(set(suggestion.source_ids) & selected)
        section = "education" if suggestion.section == "certifications" else suggestion.section
        return section in sections

    kept = [s for s in suggestions if not replaced(s)]
    removed_units = {s.unit for s in suggestions if replaced(s)}
    merged = kept + generation.suggestions
    units = removed_units | {s.unit for s in generation.suggestions}
    content = compose(content, state.original, merged, units)
    rewrite.mode = mode
    return save_version(
        db,
        state,
        content=content,
        suggestions=merged,
        generation=generation.info,
        source="regenerate",
        settings=settings,
    )


def update(
    db: Session, *, user_id: str, rewrite: ResumeRewrite, request: RewriteUpdate, settings: Settings
) -> RewriteVersion | None:
    """Rename, change template, apply decisions, save edited content, or restore an earlier version."""

    _check_base(rewrite, request.base_version)
    if request.name is not None:
        rewrite.name = request.name.strip()
        rewrite.updated_at = datetime.now(UTC)
    if request.template is not None:
        rewrite.template = request.template
        rewrite.updated_at = datetime.now(UTC)
    if request.content is None and request.decisions is None and request.restore_version is None:
        db.flush()
        return None

    state = load_state(db, user_id=user_id, rewrite=rewrite)
    content, suggestions, generation = _parse_version(current_version(db, rewrite))

    if request.decisions is not None:
        by_id = {s.id: s for s in suggestions}
        units: set[str] = set()
        for suggestion_id, decision in request.decisions.items():
            suggestion = by_id.get(suggestion_id)
            if suggestion is None:
                raise AppError("Unknown suggestion.", code="unknown_suggestion", status_code=404)
            if decision == "accepted" and suggestion.verification.status == "rejected":
                raise AppError(
                    "This suggestion makes a claim your resume does not support, so it cannot be accepted. You can "
                    "edit the text yourself instead.",
                    code="suggestion_blocked",
                    status_code=409,
                )
            suggestion.decision = decision
            units.add(suggestion.unit)
        content = compose(content, state.original, suggestions, units)
        source = "decisions"
    elif request.content is not None:
        content = request.content
        source = "edit"
    else:
        assert request.restore_version is not None
        target = rewrites_repo.get_version(db, user_id=user_id, rewrite_id=rewrite.id, number=request.restore_version)
        if target is None:
            raise AppError("That version no longer exists.", code="not_found", status_code=404)
        content, suggestions, generation = _parse_version(target)
        source = "restore"

    return save_version(
        db, state, content=content, suggestions=suggestions, generation=generation, source=source, settings=settings
    )
