"""Operator commands: ``python -m app.cli <command>`` (run from ``backend/``).

Commands
--------
check-config
    Load and validate the configuration (exactly as the server would) and print a
    summary without secrets. Exits 1 with a readable list of problems otherwise.
migrate
    Apply pending database migrations (``alembic upgrade head``). On PostgreSQL an
    advisory lock makes concurrent runs safe; the second waits, then has nothing to do.
list-unowned
    Show analyses created before accounts existed (``user_id IS NULL``).
assign-history --email EMAIL [--ids 1,2] [--dry-run] [--yes]
    Assign unowned analyses to an existing account. Takes a database backup
    (SQLite) or requires confirmation that one exists (PostgreSQL), changes
    rows in one transaction, verifies the result, and writes a rollback
    manifest. Rows that already have an owner are never touched.
rollback-history-assignment --manifest FILE [--yes]
    Undo an assignment using the manifest written by ``assign-history``.

History is never assigned automatically (for example to the first account
registered); an operator must run ``assign-history`` deliberately.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, inspect, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, Settings, get_settings
from app.db.migrate import current_revision, head_revision, run_migrations_exclusively
from app.db.models import Analysis, User
from app.db.session import Database

DEFAULT_BACKUP_DIR = BACKEND_DIR / "data" / "backups"
CONFIRM_ASSIGN = "assign"
CONFIRM_ROLLBACK = "rollback"


class CommandError(Exception):
    """A user-facing failure; printed without a traceback."""


@dataclass
class Io:
    out: Callable[[str], None]
    ask: Callable[[str], str]


def _default_io() -> Io:
    return Io(out=print, ask=input)


def _open_database(settings: Settings) -> Database:
    database = Database(settings.database_url)
    if settings.effective_auto_migrate:
        database.migrate()
    columns = {column["name"] for column in inspect(database.engine).get_columns("analyses")}
    if "user_id" not in columns:
        raise CommandError("The database schema is out of date. Run `alembic upgrade head` first.")
    return database


def _safe_url(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def _parse_ids(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    try:
        ids = sorted({int(part) for part in raw.split(",") if part.strip()})
    except ValueError as exc:
        raise CommandError("--ids must be a comma-separated list of integers.") from exc
    if not ids:
        raise CommandError("--ids was given but contains no ids.")
    return ids


def _unowned(db: Session, ids: list[int] | None) -> list[Analysis]:
    statement = select(Analysis).where(Analysis.user_id.is_(None)).order_by(Analysis.id)
    if ids is not None:
        statement = statement.where(Analysis.id.in_(ids))
    return list(db.scalars(statement))


def _describe(rows: Sequence[Analysis], io: Io) -> None:
    for row in rows:
        io.out(f"  #{row.id}  {row.created_at}  {row.resume_filename}  score={row.score}")


def _backup_sqlite(settings: Settings, backup_dir: Path, stamp: str) -> Path:
    source_path = make_url(settings.database_url).database
    if not source_path:
        raise CommandError("Cannot back up an in-memory SQLite database.")
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"resume_analyzer-{stamp}.db"
    source = sqlite3.connect(source_path)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)  # consistent online copy
        finally:
            target.close()
    finally:
        source.close()
    return destination


def describe_config_error(exc: ValidationError) -> str:
    """One line per problem, naming the environment variable; never echoes the offending values."""

    lines = []
    for error in exc.errors(include_input=False, include_url=False):
        field = ".".join(str(part) for part in error["loc"])
        message = str(error["msg"]).removeprefix("Value error, ")
        lines.append(f"  - {field.upper()}: {message}" if field else f"  - {message}")
    return "Configuration error:\n" + "\n".join(lines)


def cmd_check_config(settings: Settings, io: Io) -> int:
    io.out(f"Configuration OK (APP_ENV={settings.app_env})")
    io.out(f"  database: {'sqlite' if settings.is_sqlite else 'postgresql'} {_safe_url(settings.database_url)}")
    io.out(f"  ai provider: {settings.ai_provider} ({'key set' if settings.gemini_api_key else 'NO KEY'})")
    io.out(f"  allowed origins: {', '.join(settings.cors_origins)}")
    io.out(f"  secure cookies: {settings.effective_cookie_secure}")
    io.out(f"  backend access key: {'required' if settings.backend_access_key else 'not configured'}")
    io.out(f"  auto-migrate at start-up: {settings.effective_auto_migrate}")
    return 0


def cmd_migrate(settings: Settings, io: Io) -> int:
    url = settings.database_url
    io.out(f"Database: {_safe_url(url)}")
    before = current_revision(url)
    run_migrations_exclusively(url)
    after = current_revision(url)
    if before == after:
        io.out(f"Already up to date at revision {after}.")
    else:
        io.out(f"Migrated {before or '(empty database)'} -> {after}.")
    if after != head_revision():
        raise CommandError(f"Database is at {after}, expected head {head_revision()}.")
    return 0


def cmd_list_unowned(settings: Settings, io: Io) -> int:
    database = _open_database(settings)
    try:
        with database.session() as db:
            rows = _unowned(db, None)
        io.out(f"{len(rows)} unowned analyses in {_safe_url(settings.database_url)}")
        _describe(rows, io)
        return 0
    finally:
        database.dispose()


def cmd_assign_history(args: argparse.Namespace, settings: Settings, io: Io) -> int:
    ids = _parse_ids(args.ids)
    email = args.email.strip().lower()
    database = _open_database(settings)
    try:
        with database.session() as db:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                raise CommandError(f"No account with email {email!r}. Register it in the app first.")
            rows = _unowned(db, ids)
            if ids is not None:
                missing = sorted(set(ids) - {row.id for row in rows})
                if missing:
                    raise CommandError(
                        f"These ids do not exist or already have an owner and will not be changed: {missing}"
                    )
            if not rows:
                io.out("Nothing to assign: there are no unowned analyses.")
                return 0

            target_ids = [row.id for row in rows]
            io.out(f"Database: {_safe_url(settings.database_url)}")
            io.out(f"Assign {len(rows)} analyses to {user.email} (user id {user.id}):")
            _describe(rows, io)
            user_id = user.id

        if args.dry_run:
            io.out("Dry run: no changes made.")
            return 0

        if not args.yes and io.ask(f"Type '{CONFIRM_ASSIGN}' to continue: ").strip() != CONFIRM_ASSIGN:
            io.out("Aborted: no changes made.")
            return 2

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_dir: Path = args.backup_dir
        backup_path: Path | None = None
        if database.is_sqlite:
            backup_path = _backup_sqlite(settings, backup_dir, stamp)
            io.out(f"Backup written: {backup_path}")
        elif not args.postgres_backup_confirmed:
            raise CommandError(
                'Take a backup first (e.g. `pg_dump --format=custom --file=backup.dump "$DATABASE_URL"`, or a '
                "Render on-demand backup), then re-run with --postgres-backup-confirmed."
            )

        with database.session() as db, db.begin():
            result = db.execute(
                update(Analysis)
                .where(Analysis.id.in_(target_ids), Analysis.user_id.is_(None))
                .values(user_id=user_id)
                .execution_options(synchronize_session=False)
            )
            changed = int(getattr(result, "rowcount", 0) or 0)
            if changed != len(target_ids):
                raise CommandError(
                    f"Expected to update {len(target_ids)} rows but updated {changed}; rolled back. "
                    "Another process may have changed these rows."
                )

        with database.session() as db:
            owned = db.scalar(
                select(func.count())
                .select_from(Analysis)
                .where(Analysis.id.in_(target_ids), Analysis.user_id == user_id)
            )
        if owned != len(target_ids):
            raise CommandError(f"Verification failed: {owned} of {len(target_ids)} rows are owned by the account.")

        backup_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = backup_dir / f"history-assignment-{stamp}.json"
        manifest: dict[str, Any] = {
            "action": "assign-history",
            "created_at": datetime.now(UTC).isoformat(),
            "database": _safe_url(settings.database_url),
            "user_id": user_id,
            "email": email,
            "analysis_ids": target_ids,
            "backup_path": str(backup_path) if backup_path else None,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2))

        io.out(f"Verified: {owned} analyses now belong to {email}.")
        io.out(f"Rollback manifest: {manifest_path}")
        io.out(f"To undo: python -m app.cli rollback-history-assignment --manifest {manifest_path}")
        if backup_path:
            live_path = make_url(settings.database_url).database
            io.out(f"Or restore the full backup (server stopped): cp {backup_path} {live_path}")
        return 0
    finally:
        database.dispose()


def cmd_rollback(args: argparse.Namespace, settings: Settings, io: Io) -> int:
    try:
        manifest = json.loads(Path(args.manifest).read_text())
        user_id = str(manifest["user_id"])
        ids = [int(value) for value in manifest["analysis_ids"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CommandError(f"Could not read manifest {args.manifest}: {exc}") from exc
    if manifest.get("action") != "assign-history":
        raise CommandError("This file is not an assign-history manifest.")

    database = _open_database(settings)
    try:
        io.out(f"Database: {_safe_url(settings.database_url)}")
        io.out(f"Return {len(ids)} analyses owned by user {user_id} to the unowned state.")
        if not args.yes and io.ask(f"Type '{CONFIRM_ROLLBACK}' to continue: ").strip() != CONFIRM_ROLLBACK:
            io.out("Aborted: no changes made.")
            return 2

        with database.session() as db, db.begin():
            result = db.execute(
                update(Analysis)
                .where(Analysis.id.in_(ids), Analysis.user_id == user_id)
                .values(user_id=None)
                .execution_options(synchronize_session=False)
            )
            changed = int(getattr(result, "rowcount", 0) or 0)

        with database.session() as db:
            still_owned = db.scalar(
                select(func.count()).select_from(Analysis).where(Analysis.id.in_(ids), Analysis.user_id == user_id)
            )
        if still_owned:
            raise CommandError(f"Verification failed: {still_owned} rows are still owned by the account.")
        io.out(f"Rolled back {changed} analyses ({len(ids) - changed} were already unowned or deleted).")
        return 0
    finally:
        database.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("check-config", help="Validate the configuration and print a summary (no secrets).")
    commands.add_parser("migrate", help="Apply pending database migrations (safe to run concurrently).")
    commands.add_parser("list-unowned", help="List analyses that have no owner.")

    assign = commands.add_parser("assign-history", help="Assign unowned analyses to an account.")
    assign.add_argument("--email", required=True, help="Email of an existing account.")
    assign.add_argument("--ids", help="Comma-separated analysis ids (default: all unowned analyses).")
    assign.add_argument("--dry-run", action="store_true", help="Show what would change; change nothing.")
    assign.add_argument("--yes", action="store_true", help="Do not prompt for confirmation.")
    assign.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    assign.add_argument(
        "--postgres-backup-confirmed",
        action="store_true",
        help="Required on PostgreSQL: confirms a backup was taken (the command cannot run pg_dump for you).",
    )

    rollback = commands.add_parser("rollback-history-assignment", help="Undo an assign-history run.")
    rollback.add_argument("--manifest", required=True, type=Path)
    rollback.add_argument("--yes", action="store_true", help="Do not prompt for confirmation.")
    return parser


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None, io: Io | None = None) -> int:
    args = build_parser().parse_args(argv)
    io = io or _default_io()
    if settings is None:
        try:
            settings = get_settings()
        except ValidationError as exc:
            io.out(describe_config_error(exc))
            return 1
    try:
        if args.command == "check-config":
            return cmd_check_config(settings, io)
        if args.command == "migrate":
            return cmd_migrate(settings, io)
        if args.command == "list-unowned":
            return cmd_list_unowned(settings, io)
        if args.command == "assign-history":
            return cmd_assign_history(args, settings, io)
        return cmd_rollback(args, settings, io)
    except CommandError as exc:
        io.out(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
