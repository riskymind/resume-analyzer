"""Programmatic Alembic entry point (used at startup, in tests and by the container entrypoint)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(url: str) -> Config:
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "app" / "db" / "migrations"))
    # ConfigParser treats '%' as interpolation; escape it (URL-encoded passwords).
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


# Arbitrary constant identifying "schema migration" in pg_advisory_lock (any app-unique bigint).
MIGRATION_LOCK_ID = 7_312_640_225


def run_migrations(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def run_migrations_exclusively(url: str, revision: str = "head") -> None:
    """Upgrade, serialised across processes on PostgreSQL.

    A session-level advisory lock is held on a separate connection for the whole upgrade, so two
    instances (or a pre-deploy job racing a start-up migration) never apply the same revision twice;
    the second waits, then finds nothing to do. SQLite is single-host and just upgrades.
    """

    if make_url(url).get_backend_name() != "postgresql":
        run_migrations(url, revision)
        return
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as lock_connection:
            lock_connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
            try:
                run_migrations(url, revision)
            finally:
                lock_connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID})
    finally:
        engine.dispose()


def current_revision(url: str) -> str | None:
    """The revision recorded in the database (``None`` for an empty database)."""

    from alembic.runtime.migration import MigrationContext

    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def head_revision() -> str | None:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()


def downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)
