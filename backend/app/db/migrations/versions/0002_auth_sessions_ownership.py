"""Accounts: users, sessions, shared rate-limit buckets, and analysis ownership.

Existing analyses keep ``user_id = NULL``. They are NOT assigned to any user
automatically; use ``python -m app.cli assign-history`` (see docs/auth.md).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_sessions_user_id_users"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "rate_limits",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("window_start", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("key", "window_start", name="pk_rate_limits"),
    )
    op.create_index("ix_rate_limits_expires_at", "rate_limits", ["expires_at"])

    with op.batch_alter_table("analyses", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_analyses_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_analyses_user_id", ["user_id"])


def downgrade() -> None:
    with op.batch_alter_table("analyses", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_index("ix_analyses_user_id")
        batch.drop_constraint("fk_analyses_user_id_users", type_="foreignkey")
        batch.drop_column("user_id")

    op.drop_index("ix_rate_limits_expires_at", table_name="rate_limits")
    op.drop_table("rate_limits")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
