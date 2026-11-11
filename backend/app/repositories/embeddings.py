"""Embedding cache persistence. Entries are immutable; concurrent inserts of the same key are ignored."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.db.models import EmbeddingCacheEntry


def get_many(db: Session, keys: list[str]) -> dict[str, list[float]]:
    if not keys:
        return {}
    rows = db.execute(
        select(EmbeddingCacheEntry.key, EmbeddingCacheEntry.vector).where(EmbeddingCacheEntry.key.in_(keys))
    )
    return {key: list(vector) for key, vector in rows}


def put_many(db: Session, entries: list[dict[str, Any]]) -> None:
    """Insert cache entries, ignoring keys another request stored first."""

    if not entries:
        return
    dialect = db.get_bind().dialect.name
    insert: Any = postgresql.insert if dialect == "postgresql" else sqlite.insert
    db.execute(insert(EmbeddingCacheEntry.__table__).values(entries).on_conflict_do_nothing(index_elements=["key"]))
