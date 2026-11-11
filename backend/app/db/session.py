"""Engine and session management.

Business logic only ever sees a SQLAlchemy ``Session``; whether it is backed
by SQLite (local/tests) or PostgreSQL (production) is decided purely by
``DATABASE_URL``.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.migrate import run_migrations_exclusively


class Database:
    def __init__(self, url: str, *, self_heal: bool = False) -> None:
        self.url = url
        parsed = make_url(url)
        self.is_sqlite = parsed.get_backend_name() == "sqlite"
        self._sqlite_path: Path | None = None
        connect_args: dict[str, Any] = {}

        if self.is_sqlite:
            connect_args["check_same_thread"] = False
            if parsed.database and parsed.database != ":memory:":
                self._sqlite_path = Path(parsed.database)
                self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine: Engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        if self.is_sqlite:
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)

        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        # Local-dev convenience preserved from the original app: if the SQLite
        # file is deleted while the server runs, recreate the schema instead
        # of failing every request.
        self._self_heal = self_heal and self._sqlite_path is not None
        self._heal_lock = threading.Lock()

    def migrate(self) -> None:
        run_migrations_exclusively(self.url)

    def session(self) -> Session:
        if self._self_heal and self._sqlite_path is not None and not self._sqlite_path.exists():
            with self._heal_lock:
                if not self._sqlite_path.exists():
                    self.engine.dispose()
                    self.migrate()
        return self.session_factory()

    def dispose(self) -> None:
        self.engine.dispose()


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
