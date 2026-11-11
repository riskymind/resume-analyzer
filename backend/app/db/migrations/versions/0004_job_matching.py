"""Job descriptions, requirements, deterministic job matches, matching configs and the embedding cache.

Also links fit analyses created through ``/api/analyze`` to the job match that
now produces their score (``analyses.job_match_id``). Existing analyses keep
``job_match_id = NULL`` and their original scores.

Rollback: ``alembic downgrade 0003`` drops the new tables and the link column.
Job descriptions and match reports created since this migration are lost;
resumes, quality reports and fit-analysis history are preserved.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _user_fk(table: str, *, nullable: bool = False) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "user_id",
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="CASCADE", name=f"fk_{table}_user_id_users"),
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "matching_configs",
        sa.Column("version", sa.String(40), primary_key=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "job_descriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        _user_fk("job_descriptions"),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_format", sa.String(16), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("structured", sa.JSON(), nullable=False),
        sa.Column("extraction_version", sa.String(40), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_descriptions_user_id", "job_descriptions", ["user_id"])
    op.create_index("ix_job_descriptions_user_id_created_at", "job_descriptions", ["user_id", "created_at"])

    op.create_table(
        "job_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_description_id",
            sa.String(36),
            sa.ForeignKey(
                "job_descriptions.id",
                ondelete="CASCADE",
                name="fk_job_requirements_job_description_id_job_descriptions",
            ),
            nullable=False,
        ),
        _user_fk("job_requirements"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("requirement_key", sa.String(16), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("classification_source", sa.String(16), nullable=False),
        sa.Column("importance", sa.String(16), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("min_years", sa.Float(), nullable=True),
        sa.Column("alternative_group", sa.String(16), nullable=True),
    )
    op.create_index("ix_job_requirements_job_description_id", "job_requirements", ["job_description_id"])
    op.create_index("ix_job_requirements_user_id", "job_requirements", ["user_id"])

    op.create_table(
        "job_matches",
        sa.Column("id", sa.String(36), primary_key=True),
        _user_fk("job_matches"),
        sa.Column(
            "resume_id",
            sa.String(36),
            sa.ForeignKey("resumes.id", ondelete="CASCADE", name="fk_job_matches_resume_id_resumes"),
            nullable=False,
        ),
        sa.Column(
            "job_description_id",
            sa.String(36),
            sa.ForeignKey(
                "job_descriptions.id", ondelete="CASCADE", name="fk_job_matches_job_description_id_job_descriptions"
            ),
            nullable=False,
        ),
        sa.Column(
            "matching_version",
            sa.String(40),
            sa.ForeignKey("matching_configs.version", name="fk_job_matches_matching_version_matching_configs"),
            nullable=False,
        ),
        sa.Column("match_score", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("semantic_status", sa.String(16), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_matches_user_id", "job_matches", ["user_id"])
    op.create_index("ix_job_matches_user_id_created_at", "job_matches", ["user_id", "created_at"])
    op.create_index("ix_job_matches_resume_id", "job_matches", ["resume_id"])
    op.create_index("ix_job_matches_job_description_id", "job_matches", ["job_description_id"])

    op.create_table(
        "embedding_cache",
        sa.Column("key", sa.String(64), primary_key=True),
        _user_fk("embedding_cache", nullable=True),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_embedding_cache_user_id", "embedding_cache", ["user_id"])
    op.create_index("ix_embedding_cache_created_at", "embedding_cache", ["created_at"])

    with op.batch_alter_table("analyses", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("job_match_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_analyses_job_match_id_job_matches", "job_matches", ["job_match_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_index("ix_analyses_job_match_id", ["job_match_id"])


def downgrade() -> None:
    with op.batch_alter_table("analyses", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_index("ix_analyses_job_match_id")
        batch.drop_constraint("fk_analyses_job_match_id_job_matches", type_="foreignkey")
        batch.drop_column("job_match_id")

    op.drop_index("ix_embedding_cache_created_at", table_name="embedding_cache")
    op.drop_index("ix_embedding_cache_user_id", table_name="embedding_cache")
    op.drop_table("embedding_cache")
    for name in ("job_description_id", "resume_id", "user_id_created_at", "user_id"):
        op.drop_index(f"ix_job_matches_{name}", table_name="job_matches")
    op.drop_table("job_matches")
    op.drop_index("ix_job_requirements_user_id", table_name="job_requirements")
    op.drop_index("ix_job_requirements_job_description_id", table_name="job_requirements")
    op.drop_table("job_requirements")
    op.drop_index("ix_job_descriptions_user_id_created_at", table_name="job_descriptions")
    op.drop_index("ix_job_descriptions_user_id", table_name="job_descriptions")
    op.drop_table("job_descriptions")
    op.drop_table("matching_configs")
