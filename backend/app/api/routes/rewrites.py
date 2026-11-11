"""AI resume rewriting: create, review, edit, regenerate, version history, preview and export.

Routes stay thin: validation and ownership checks here, rules in
``app.services.rewriting.service``. Every query is scoped to the signed-in
user; another user's rewrite returns the same 404 as a missing one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
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
from app.core.errors import AppError, NotFoundError
from app.db.models import ResumeRewrite, RewriteVersion
from app.documents.render import DOCX_MIME, PDF_MIME, export_filename, render_docx, render_html, render_pdf
from app.documents.templates import template_infos
from app.repositories import jobs as jobs_repo
from app.repositories import resumes as resumes_repo
from app.repositories import rewrites as rewrites_repo
from app.schemas.rewrite import (
    ExportRequest,
    GenerationInfo,
    PreviewResponse,
    RegenerateRequest,
    ResumeDocument,
    RewriteCreate,
    RewriteDetail,
    RewriteSummary,
    RewriteUpdate,
    ScoreComparison,
    Suggestion,
    TemplateInfo,
    TemplateKey,
    VerificationSummary,
    VersionSummary,
)
from app.services.rate_limit import RateLimiter
from app.services.rewriting import service

router = APIRouter(prefix="/rewrites", tags=["rewrites"])


# --------------------------------------------------------------------------- serialisation


def _summary(
    rewrite: ResumeRewrite, version: RewriteVersion | None, resume_filename: str, job_title: str | None
) -> RewriteSummary:
    scores = ScoreComparison.model_validate(version.scores) if version else None
    return RewriteSummary(
        id=rewrite.id,
        name=rewrite.name,
        resume_id=rewrite.resume_id,
        resume_filename=resume_filename,
        job_id=rewrite.job_description_id,
        job_title=job_title,
        mode=rewrite.mode,
        template=rewrite.template,
        current_version=rewrite.current_version,
        quality_before=scores.quality.before if scores else None,
        quality_after=scores.quality.after if scores else None,
        match_before=scores.match.before if scores and scores.match else None,
        match_after=scores.match.after if scores and scores.match else None,
        verification_status=version.verification_status if version else None,
        job_detached_at=rewrite.job_detached_at,
        created_at=rewrite.created_at,
        updated_at=rewrite.updated_at,
    )


def _detail(db: Session, rewrite: ResumeRewrite, version: RewriteVersion | None = None) -> RewriteDetail:
    current = service.current_version(db, rewrite)
    shown = version or current
    resume = resumes_repo.get_resume(db, user_id=rewrite.user_id, resume_id=rewrite.resume_id)
    job = (
        jobs_repo.get_job(db, user_id=rewrite.user_id, job_id=rewrite.job_description_id)
        if rewrite.job_description_id
        else None
    )
    versions = rewrites_repo.list_versions(db, user_id=rewrite.user_id, rewrite_id=rewrite.id)
    return RewriteDetail(
        **_summary(rewrite, current, resume.filename if resume else "", job.title if job else None).model_dump(),
        version=shown.number,
        original=ResumeDocument.model_validate(rewrite.original),
        content=ResumeDocument.model_validate(shown.content),
        suggestions=[Suggestion.model_validate(s) for s in shown.suggestions],
        verification=VerificationSummary.model_validate(shown.verification),
        scores=ScoreComparison.model_validate(shown.scores),
        generation=GenerationInfo.model_validate(shown.generation),
        versions=[
            VersionSummary(
                number=row.number,
                source=row.source,
                created_at=row.created_at,
                quality_after=row.quality_after,
                match_after=row.match_after,
                verification_status=row.verification_status,
            )
            for row in versions
        ],
    )


def _load(db: Session, user_id: str, rewrite_id: str) -> ResumeRewrite:
    rewrite = rewrites_repo.get_rewrite(db, user_id=user_id, rewrite_id=rewrite_id)
    if rewrite is None:
        raise NotFoundError("Rewrite not found.")
    return rewrite


def _version(db: Session, rewrite: ResumeRewrite, number: int | None) -> RewriteVersion:
    if number is None or number == rewrite.current_version:
        return service.current_version(db, rewrite)
    version = rewrites_repo.get_version(db, user_id=rewrite.user_id, rewrite_id=rewrite.id, number=number)
    if version is None:
        raise NotFoundError("That version does not exist (older versions may have been pruned).")
    return version


def _provider_factory(
    provider: AIProvider | None, limiter: RateLimiter, settings: Settings, user_id: str
) -> service.ProviderFactory:
    def factory() -> AIProvider:
        ai = require_ai_provider(provider)
        enforce_ai_limits(limiter, settings, user_id)
        return ai

    return factory


# --------------------------------------------------------------------------- endpoints


@router.get("/templates", response_model=list[TemplateInfo])
def list_templates(_: Annotated[CurrentUser, Depends(get_current_user)]) -> list[TemplateInfo]:
    return template_infos()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RewriteDetail)
def create_rewrite(
    body: RewriteCreate,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> RewriteDetail:
    user_id = current.user.id
    resume = resumes_repo.get_resume(db, user_id=user_id, resume_id=body.resume_id)
    if resume is None:
        raise NotFoundError("Resume not found.")
    job = None
    if body.job_id is not None:
        job = jobs_repo.get_job(db, user_id=user_id, job_id=body.job_id)
        if job is None:
            raise NotFoundError("Job description not found.")
    rewrite = service.create(
        db,
        user_id=user_id,
        resume=resume,
        job_row=job,
        request=body,
        provider_factory=_provider_factory(provider, limiter, settings, user_id),
        settings=settings,
    )
    db.commit()
    return _detail(db, rewrite)


@router.get("", response_model=list[RewriteSummary])
def list_rewrites(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
    resume_id: Annotated[str | None, Query(max_length=36)] = None,
) -> list[RewriteSummary]:
    rows = rewrites_repo.list_rewrites(db, user_id=current.user.id, resume_id=resume_id)
    return [_summary(*row) for row in rows]


@router.get("/{rewrite_id}", response_model=RewriteDetail)
def get_rewrite(
    rewrite_id: str,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
    version: Annotated[int | None, Query(ge=1)] = None,
) -> RewriteDetail:
    rewrite = _load(db, current.user.id, rewrite_id)
    return _detail(db, rewrite, _version(db, rewrite, version))


@router.patch("/{rewrite_id}", response_model=RewriteDetail)
def update_rewrite(
    rewrite_id: str,
    body: RewriteUpdate,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> RewriteDetail:
    rewrite = _load(db, current.user.id, rewrite_id)
    service.update(db, user_id=current.user.id, rewrite=rewrite, request=body, settings=settings)
    db.commit()
    return _detail(db, rewrite)


@router.post("/{rewrite_id}/regenerate", response_model=RewriteDetail)
def regenerate_rewrite(
    rewrite_id: str,
    body: RegenerateRequest,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    provider: Annotated[AIProvider | None, Depends(get_optional_ai_provider)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> RewriteDetail:
    user_id = current.user.id
    rewrite = _load(db, user_id, rewrite_id)
    service.regenerate(
        db,
        user_id=user_id,
        rewrite=rewrite,
        request=body,
        provider_factory=_provider_factory(provider, limiter, settings, user_id),
        settings=settings,
    )
    db.commit()
    return _detail(db, rewrite)


@router.delete("/{rewrite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rewrite(
    rewrite_id: str,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
) -> Response:
    if not rewrites_repo.delete_rewrite(db, user_id=current.user.id, rewrite_id=rewrite_id):
        raise NotFoundError("Rewrite not found.")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{rewrite_id}/preview", response_model=PreviewResponse)
def preview_rewrite(
    rewrite_id: str,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
    template: TemplateKey | None = None,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> PreviewResponse:
    """The export layout as HTML, for display in a sandboxed iframe. The PDF is rendered from the same HTML."""

    rewrite = _load(db, current.user.id, rewrite_id)
    shown = _version(db, rewrite, version)
    key: TemplateKey = template or rewrite.template  # type: ignore[assignment]
    return PreviewResponse(
        template=key, version=shown.number, html=render_html(ResumeDocument.model_validate(shown.content), key)
    )


@router.post("/{rewrite_id}/export")
def export_rewrite(
    rewrite_id: str,
    body: ExportRequest,
    current: Annotated[CurrentUser, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> Response:
    """Generate a PDF or DOCX of the saved content on demand and stream it. Nothing is stored on disk.

    Content with unverified claims (the user's own edits, or accepted suggestions with warnings) is exported
    only with ``acknowledge_unverified: true``; otherwise ``409 acknowledgement_required``. Nothing is removed
    from the user's content, and the acknowledgement is recorded in the export metadata.
    """

    rewrite = _load(db, current.user.id, rewrite_id)
    shown = _version(db, rewrite, body.version)
    limiter.hit(
        "export:minute",
        current.user.id,
        limit=settings.export_max_per_minute,
        window_seconds=60,
        message="You're exporting too quickly. Please wait a minute and try again.",
    )
    key: TemplateKey = body.template or rewrite.template  # type: ignore[assignment]
    document = ResumeDocument.model_validate(shown.content)
    verification = VerificationSummary.model_validate(shown.verification)
    unverified = verification.blocking + verification.warnings
    if unverified and not body.acknowledge_unverified:
        raise AppError(
            f"Version {shown.number} contains {unverified} claim(s) that could not be verified against your original "
            "resume. Review them and confirm they are accurate before exporting.",
            code="acknowledgement_required",
            status_code=409,
        )
    if body.format == "pdf":
        data, media_type = render_pdf(document, key), PDF_MIME
    else:
        data, media_type = render_docx(document, key), DOCX_MIME
    rewrites_repo.record_export(
        db,
        rewrite=rewrite,
        version_number=shown.number,
        fmt=body.format,
        template=key,
        size_bytes=len(data),
        verification_status=verification.status,
        acknowledged_unverified=bool(unverified),
    )
    db.commit()
    filename = export_filename(document, rewrite.name, body.format)
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
