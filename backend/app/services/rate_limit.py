"""Database-backed fixed-window rate limiting.

Counters live in the shared database (PostgreSQL in production), so limits are
enforced consistently across uvicorn workers and service instances; nothing is
held in process memory. Each hit is a single atomic upsert
(``INSERT ... ON CONFLICT DO UPDATE ... RETURNING``) in its own short
transaction, so concurrent requests cannot both slip under the limit and the
count survives even when the surrounding request later fails (e.g. a failed
login).
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects import postgresql, sqlite

from app.core.errors import RateLimitedError
from app.db.models import RateLimitBucket
from app.db.session import Database

logger = logging.getLogger(__name__)

_PURGE_PROBABILITY = 0.02


class RateLimiter:
    def __init__(self, database: Database, *, clock: Callable[[], float] = time.time) -> None:
        self._database = database
        self._clock = clock
        dialect = database.engine.dialect.name
        if dialect == "sqlite":
            self._insert: Any = sqlite.insert
        elif dialect == "postgresql":
            self._insert = postgresql.insert
        else:  # pragma: no cover - only SQLite and PostgreSQL are supported
            raise RuntimeError(f"Rate limiting is not implemented for database dialect {dialect!r}")

    def hit(self, scope: str, identifier: str, *, limit: int, window_seconds: int, message: str) -> int:
        """Count one event for ``(scope, identifier)``; raise 429 once ``limit`` is exceeded."""

        now = int(self._clock())
        window_start = now - (now % window_seconds)
        window_end = window_start + window_seconds
        # Hash the identifier so emails and IP addresses are never stored.
        key = hashlib.sha256(f"{scope}\x00{identifier}".encode()).hexdigest()

        table = RateLimitBucket.__table__
        statement = (
            self._insert(table)
            .values(key=key, window_start=window_start, count=1, expires_at=window_end)
            .on_conflict_do_update(index_elements=["key", "window_start"], set_={"count": table.c.count + 1})
            .returning(table.c.count)
        )
        with self._database.engine.begin() as connection:
            count = int(connection.execute(statement).scalar_one())
            if random.random() < _PURGE_PROBABILITY:  # noqa: S311 - not security sensitive
                connection.execute(delete(RateLimitBucket).where(RateLimitBucket.expires_at < now))

        if count > limit:
            logger.info("rate_limited", extra={"scope": scope})
            raise RateLimitedError(message, retry_after_seconds=window_end - now)
        return count

    def purge_expired(self) -> None:
        with self._database.engine.begin() as connection:
            connection.execute(delete(RateLimitBucket).where(RateLimitBucket.expires_at < int(self._clock())))
