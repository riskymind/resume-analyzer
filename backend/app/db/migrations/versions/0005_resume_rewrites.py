"""Resume rewriting: rewrite sessions, immutable versions and export metadata.

- ``resume_rewrites``: one per rewrite session (resume, optional job, name, mode, template, original snapshot).
- ``resume_rewrite_versions``: immutable snapshots (content, suggestions, verification, recalculated scores).
- ``resume_rewrite_exports``: metadata for generated PDF/DOCX files. Files are streamed, never stored.

Purely additive: no existing table changes.

Rollback: ``alembic downgrade 0004`` drops the three tables. Rewrites created since this migration are lost;
resumes, job descriptions, matches and analyses are untouched.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(table: str, column: str, target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> sa.Column:  # type: ignore[type-arg]
    target_table = target.split(".")[0]
    return sa.Column(
        column,
        sa.String(36),
        sa.ForeignKey(target, ondelete=ondelete, name=f"fk_{table}_{column}_{target_table}"),
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "resume_rewrites",
        sa.Column("id", sa.String(36), primary_key=True),
        _fk("resume_rewrites", "user_id", "users.id"),
        _fk("resume_rewrites", "resume_id", "resumes.id"),
        _fk("resume_rewrites", "job_description_id", "job_descriptions.id", nullable=True, ondelete="SET NULL"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("template", sa.String(20), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("original", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resume_rewrites_user_id", "resume_rewrites", ["user_id"])
    op.create_index("ix_resume_rewrites_user_id_updated_at", "resume_rewrites", ["user_id", "updated_at"])
    op.create_index("ix_resume_rewrites_resume_id", "resume_rewrites", ["resume_id"])
    op.create_index("ix_resume_rewrites_job_description_id", "resume_rewrites", ["job_description_id"])

    op.create_table(
        "resume_rewrite_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        _fk("resume_rewrite_versions", "rewrite_id", "resume_rewrites.id"),
        _fk("resume_rewrite_versions", "user_id", "users.id"),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("suggestions", sa.JSON(), nullable=False),
        sa.Column("verification", sa.JSON(), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("generation", sa.JSON(), nullable=False),
        sa.Column("verification_status", sa.String(20), nullable=False),
        sa.Column("quality_after", sa.Integer(), nullable=False),
        sa.Column("match_after", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("rewrite_id", "number", name="uq_resume_rewrite_versions_rewrite_id_number"),
    )
    op.create_index("ix_resume_rewrite_versions_rewrite_id", "resume_rewrite_versions", ["rewrite_id"])
    op.create_index("ix_resume_rewrite_versions_user_id", "resume_rewrite_versions", ["user_id"])

    op.create_table(
        "resume_rewrite_exports",
        sa.Column("id", sa.String(36), primary_key=True),
        _fk("resume_rewrite_exports", "user_id", "users.id"),
        _fk("resume_rewrite_exports", "rewrite_id", "resume_rewrites.id"),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("template", sa.String(20), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resume_rewrite_exports_user_id", "resume_rewrite_exports", ["user_id"])
    op.create_index("ix_resume_rewrite_exports_rewrite_id", "resume_rewrite_exports", ["rewrite_id"])


def downgrade() -> None:
    op.drop_index("ix_resume_rewrite_exports_rewrite_id", table_name="resume_rewrite_exports")
    op.drop_index("ix_resume_rewrite_exports_user_id", table_name="resume_rewrite_exports")
    op.drop_table("resume_rewrite_exports")
    op.drop_index("ix_resume_rewrite_versions_user_id", table_name="resume_rewrite_versions")
    op.drop_index("ix_resume_rewrite_versions_rewrite_id", table_name="resume_rewrite_versions")
    op.drop_table("resume_rewrite_versions")
    for name in ("job_description_id", "resume_id", "user_id_updated_at", "user_id"):
        op.drop_index(f"ix_resume_rewrites_{name}", table_name="resume_rewrites")
    op.drop_table("resume_rewrites")
