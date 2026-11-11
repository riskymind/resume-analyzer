"""Rewrite job detachment marker and export acknowledgement metadata.

- ``resume_rewrites.job_detached_at``: when the rewrite's target job was deleted. The rewrite and its versions
  are kept; job-derived data is removed from them (see ``repositories/rewrites.detach_job``).
- ``resume_rewrite_exports.verification_status``: verification status of the exported version.
- ``resume_rewrite_exports.acknowledged_unverified``: whether the user confirmed claims that could not be
  verified against the original resume before exporting.

Purely additive (nullable columns, or a server default), so existing rows stay valid.

Rollback: ``alembic downgrade 0005`` drops the three columns. Detachment timestamps and acknowledgement
records are lost; rewrites, versions and other export metadata are untouched.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("resume_rewrites") as batch:
        batch.add_column(sa.Column("job_detached_at", UTCDateTime(), nullable=True))
    with op.batch_alter_table("resume_rewrite_exports") as batch:
        batch.add_column(sa.Column("verification_status", sa.String(20), nullable=True))
        batch.add_column(sa.Column("acknowledged_unverified", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("resume_rewrite_exports") as batch:
        batch.drop_column("acknowledged_unverified")
        batch.drop_column("verification_status")
    with op.batch_alter_table("resume_rewrites") as batch:
        batch.drop_column("job_detached_at")
