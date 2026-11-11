"""ORM models. Schema changes are made through Alembic migrations, never ``create_all``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import false as sa_false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import UTCDateTime, utcnow


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    # Random UUIDs, so user ids are not enumerable.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow)


class AuthSession(Base):
    """A server-side login session. Only a SHA-256 hash of the cookie token is stored."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Synchronizer CSRF token bound to this session. Not a credential on its
    # own (useless without the HttpOnly session cookie), so it is stored as-is
    # in order to be returned to the client on /auth/me after a page reload.
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class RateLimitBucket(Base):
    """Fixed-window counters shared by all workers/instances through the database.

    ``key`` is a SHA-256 digest, so IP addresses and emails are not stored.
    """

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)


class Resume(Base):
    """An uploaded resume: extracted text and verified structure. The original file is never stored."""

    __tablename__ = "resumes"
    __table_args__ = (Index("ix_resumes_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(String(16), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    structured: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow)


class ResumeAnalysis(Base):
    """A deterministic quality report for a resume, tagged with the scoring version that produced it."""

    __tablename__ = "resume_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    resume_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scoring_version: Mapped[str] = mapped_column(String(40), nullable=False)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    ats_score: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class Analysis(Base):
    """Resume-vs-JD fit analysis (schema inherited from the original app).

    ``created_at`` stays an ISO-8601 UTC string for compatibility with rows
    written before the refactor. ``user_id`` is NULL only for rows created
    before accounts existed; those are visible to nobody until explicitly
    assigned with ``python -m app.cli assign-history``.
    """

    __tablename__ = "analyses"
    __table_args__ = {"sqlite_autoincrement": True}  # noqa: RUF012 - SQLAlchemy declarative hook

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Set for analyses created since structured resumes were introduced (Milestone 3).
    resume_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Set for analyses created since deterministic job matching was introduced (Milestone 4).
    job_match_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job_matches.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    resume_filename: Mapped[str] = mapped_column(Text, nullable=False)
    jd_source: Mapped[str] = mapped_column(Text, nullable=False)
    resume_text: Mapped[str] = mapped_column(Text, nullable=False)
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    score_label: Mapped[str] = mapped_column(Text, nullable=False)
    recommendations_json: Mapped[str] = mapped_column(Text, nullable=False)


class MatchingConfigRecord(Base):
    """An immutable snapshot of a job-matching configuration, referenced by every match it produced."""

    __tablename__ = "matching_configs"

    version: Mapped[str] = mapped_column(String(40), primary_key=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class JobDescription(Base):
    """A submitted job description: its text, verified job information and keywords."""

    __tablename__ = "job_descriptions"
    __table_args__ = (Index("ix_job_descriptions_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # "pasted" or the uploaded filename
    source_format: Mapped[str] = mapped_column(String(16), nullable=False)  # text | pdf | docx | markdown
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    # info, keywords and extraction metadata; requirements live in job_requirements.
    structured: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(40), nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow)


class JobRequirementRecord(Base):
    __tablename__ = "job_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_description_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    requirement_key: Mapped[str] = mapped_column(String(16), nullable=False)  # "r1", "r2", ...
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    classification_source: Mapped[str] = mapped_column(String(16), nullable=False)
    importance: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    min_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    alternative_group: Mapped[str | None] = mapped_column(String(16), nullable=True)


class JobMatch(Base):
    """A deterministic resume-vs-job match report and the exact inputs needed to reproduce it."""

    __tablename__ = "job_matches"
    __table_args__ = (Index("ix_job_matches_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_description_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    matching_version: Mapped[str] = mapped_column(String(40), ForeignKey("matching_configs.version"), nullable=False)
    match_score: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    semantic_status: Mapped[str] = mapped_column(String(16), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # as_of date and the semantic similarities used, so the score can be recomputed exactly.
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class EmbeddingCacheEntry(Base):
    """Cached embedding vectors.

    Short skill/requirement terms ("Kubernetes") are shared (``user_id`` NULL).
    Longer texts such as experience bullets are personal data: they are cached
    per user and deleted with the account.
    """

    __tablename__ = "embedding_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow, index=True)


class ResumeRewrite(Base):
    """A rewrite session: a resume, an optional target job, and a history of versions.

    ``original`` is a snapshot of the source resume as an editable document, so
    verification and before/after scores always compare against the same
    baseline. The source resume itself is never modified.
    """

    __tablename__ = "resume_rewrites"
    __table_args__ = (Index("ix_resume_rewrites_user_id_updated_at", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Deleting the job keeps the rewrite (it is the user's work) but unlinks it.
    job_description_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job_descriptions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    template: Mapped[str] = mapped_column(String(20), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False)
    original: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Set when the target job is deleted; the rewrite is kept without job-derived data.
    job_detached_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow)


class RewriteVersion(Base):
    """An immutable snapshot of a rewrite: content, suggestions, verification and recalculated scores."""

    __tablename__ = "resume_rewrite_versions"
    __table_args__ = (UniqueConstraint("rewrite_id", "number", name="uq_resume_rewrite_versions_rewrite_id_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rewrite_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resume_rewrites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    # generate | regenerate | decisions | edit | restore
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    suggestions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    verification: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    generation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Denormalised for listings.
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)
    quality_after: Mapped[int] = mapped_column(Integer, nullable=False)
    match_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class RewriteExport(Base):
    """Metadata about a generated export. The file itself is streamed and never stored."""

    __tablename__ = "resume_rewrite_exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rewrite_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resume_rewrites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    template: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    verification_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The user confirmed unverified claims (their own edits or accepted warnings) before exporting.
    acknowledged_unverified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_false()
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
