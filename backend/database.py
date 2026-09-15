"""SQLite connection and schema initialization.

No external migration tool is used at this project's scope. Schema creation
(`CREATE TABLE IF NOT EXISTS`) runs on every connection rather than once at
app startup, so the app self-heals if `resume_analyzer.db` is deleted or
reset by hand while the server keeps running — a routine local-dev action.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_PATH = Path(__file__).resolve().parent.parent / "resume_analyzer.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    resume_filename TEXT NOT NULL,
    jd_source TEXT NOT NULL,
    resume_text TEXT NOT NULL,
    jd_text TEXT NOT NULL,
    score INTEGER NOT NULL,
    score_label TEXT NOT NULL,
    recommendations_json TEXT NOT NULL
)
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Open a connection to the SQLite database as a context manager.

    Ensures the schema exists, commits on a clean exit (or rolls back on an
    exception), then always closes the connection — callers just use
    `with get_connection() as conn:`.
    """

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            conn.execute(_SCHEMA)
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Ensure the database schema exists. Called once at app startup."""

    with get_connection():
        pass
