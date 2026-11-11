"""Structured resumes and deterministic quality reports.

Adds ``resumes`` (extracted text, detected sections, verified structure; the
original file is never stored) and ``resume_analyses`` (quality reports), and
links new fit analyses to their resume via ``analyses.resume_id``. Existing
analyses keep ``resume_id = NULL`` and are otherwise untouched.

Rollback: ``alembic downgrade 0002`` drops both tables and the link column
(structured resume data created since this migration is lost; legacy analysis
history is preserved).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resumes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_resumes_user_id_users"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("file_format", sa.String(16), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("structured", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])
    op.create_index("ix_resumes_user_id_created_at", "resumes", ["user_id", "created_at"])

    op.create_table(
        "resume_analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "resume_id",
            sa.String(36),
            sa.ForeignKey("resumes.id", ondelete="CASCADE", name="fk_resume_analyses_resume_id_resumes"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_resume_analyses_user_id_users"),
            nullable=False,
        ),
        sa.Column("scoring_version", sa.String(40), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("ats_score", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_resume_analyses_resume_id", "resume_analyses", ["resume_id"])
    op.create_index("ix_resume_analyses_user_id", "resume_analyses", ["user_id"])

    with op.batch_alter_table("analyses", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("resume_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_analyses_resume_id_resumes", "resumes", ["resume_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_analyses_resume_id", ["resume_id"])


def downgrade() -> None:
    with op.batch_alter_table("analyses", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_index("ix_analyses_resume_id")
        batch.drop_constraint("fk_analyses_resume_id_resumes", type_="foreignkey")
        batch.drop_column("resume_id")

    op.drop_index("ix_resume_analyses_user_id", table_name="resume_analyses")
    op.drop_index("ix_resume_analyses_resume_id", table_name="resume_analyses")
    op.drop_table("resume_analyses")
    op.drop_index("ix_resumes_user_id_created_at", table_name="resumes")
    op.drop_index("ix_resumes_user_id", table_name="resumes")
    op.drop_table("resumes")
