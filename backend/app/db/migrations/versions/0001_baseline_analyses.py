"""Baseline: the original `analyses` table, plus a created_at index.

Databases created by the pre-refactor app already contain `analyses` (built by
`CREATE TABLE IF NOT EXISTS`) but have no Alembic version table. This
migration adopts such a table in place, so existing local history survives.

Revision ID: 0001
Revises:
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("analyses"):
        op.create_table(
            "analyses",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("resume_filename", sa.Text(), nullable=False),
            sa.Column("jd_source", sa.Text(), nullable=False),
            sa.Column("resume_text", sa.Text(), nullable=False),
            sa.Column("jd_text", sa.Text(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("score_label", sa.Text(), nullable=False),
            sa.Column("recommendations_json", sa.Text(), nullable=False),
            sqlite_autoincrement=True,
        )

    existing_indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("analyses")}
    if "ix_analyses_created_at" not in existing_indexes:
        op.create_index("ix_analyses_created_at", "analyses", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_analyses_created_at", table_name="analyses")
    op.drop_table("analyses")
