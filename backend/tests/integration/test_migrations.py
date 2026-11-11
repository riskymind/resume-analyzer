"""Database migrations: fresh install, legacy-DB adoption, round trip, dev self-heal."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlalchemy as sa
from fastapi.testclient import TestClient

from app import cli
from app.application import create_app
from app.db.migrate import downgrade, run_migrations
from tests.conftest import FakeLLM, make_settings, sign_up

# Exact DDL used by the pre-refactor app (backend/database.py at ac8d085).
LEGACY_DDL = """
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


def _url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _tables(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_fresh_database_gets_schema_and_version(tmp_path: Path) -> None:
    url = _url(tmp_path / "fresh.db")
    run_migrations(url)
    assert {"analyses", "alembic_version"} <= _tables(url)
    engine = sa.create_engine(url)
    indexes = {ix["name"] for ix in sa.inspect(engine).get_indexes("analyses")}
    engine.dispose()
    assert "ix_analyses_created_at" in indexes


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    url = _url(tmp_path / "twice.db")
    run_migrations(url)
    run_migrations(url)
    assert "analyses" in _tables(url)


def test_downgrade_and_upgrade_round_trip(tmp_path: Path) -> None:
    url = _url(tmp_path / "roundtrip.db")
    run_migrations(url)
    downgrade(url, "base")
    assert "analyses" not in _tables(url)
    run_migrations(url)
    assert "analyses" in _tables(url)


def _create_legacy_db(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    connection.execute(LEGACY_DDL)
    connection.execute(
        "INSERT INTO analyses (created_at, resume_filename, jd_source, resume_text, jd_text, score, score_label, "
        "recommendations_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-11-01T10:00:00+00:00",
            "old.pdf",
            "pasted",
            "resume text",
            "jd text",
            64,
            "Good Match",
            '{"missing_keywords": ["Go"], "phrasing_suggestions": [], "skill_gaps": [], "formatting_notes": []}',
        ),
    )
    connection.commit()
    connection.close()


def test_legacy_rows_survive_and_stay_private_until_explicitly_assigned(tmp_path: Path, fake_llm: FakeLLM) -> None:
    db_path = tmp_path / "legacy.db"
    _create_legacy_db(db_path)
    settings = make_settings(tmp_path, database_url=_url(db_path))

    with TestClient(create_app(settings, ai_provider=fake_llm)) as client:
        sign_up(client, "first@example.com")
        # Never auto-assigned to the first account registered.
        assert client.get("/api/analyses").json() == []

    rows = sqlite3.connect(db_path).execute("SELECT resume_filename, user_id FROM analyses").fetchall()
    assert rows == [("old.pdf", None)]

    output: list[str] = []
    io = cli.Io(out=output.append, ask=lambda _: "assign")
    code = cli.main(
        ["assign-history", "--email", "first@example.com", "--backup-dir", str(tmp_path / "backups")],
        settings=settings,
        io=io,
    )
    assert code == 0, output

    with TestClient(create_app(settings, ai_provider=fake_llm)) as client:
        client.post("/api/v1/auth/login", json={"email": "first@example.com", "password": "correct horse battery"})
        listing = client.get("/api/analyses").json()
        assert [(item["resume_filename"], item["score"]) for item in listing] == [("old.pdf", 64)]
        detail = client.get(f"/api/analyses/{listing[0]['id']}").json()
        assert detail["result"]["recommendations"]["missing_keywords"] == ["Go"]


def test_dev_self_heal_recreates_deleted_sqlite_file(tmp_path: Path, fake_llm: FakeLLM) -> None:
    """Preserves the original app's behaviour when the local DB file is deleted mid-session."""

    db_path = tmp_path / "heal.db"
    settings = make_settings(tmp_path, database_url=_url(db_path), app_env="development")
    with TestClient(create_app(settings, ai_provider=fake_llm)) as client:
        sign_up(client)
        client.post("/api/analyze", files={"resume": ("a.md", b"# A", "text/markdown")}, data={"jd_text": "jd"})
        assert len(client.get("/api/analyses").json()) == 1
        db_path.unlink()
        # A fresh schema is created instead of a 500. The session lived in the
        # deleted file, so the user is simply signed out, and stale rows are
        # not served from a pooled connection to the deleted file.
        assert client.get("/api/analyses").status_code == 401
        assert db_path.exists()
        sign_up(client)
        assert client.get("/api/analyses").json() == []


def test_0003_upgrade_preserves_accounts_and_history_and_downgrades_cleanly(tmp_path: Path, fake_llm: FakeLLM) -> None:
    db_path = tmp_path / "m3.db"
    url = _url(db_path)
    _create_legacy_db(db_path)
    run_migrations(url, "0002")  # state before Milestone 3, with a real account and an assigned analysis
    settings = make_settings(tmp_path, database_url=url, auto_migrate=False)
    connection = sqlite3.connect(db_path)
    connection.execute(
        "INSERT INTO users (id, email, password_hash, created_at, updated_at) "
        "VALUES ('u1', 'owner@example.com', 'x', '2026-11-01 00:00:00', '2026-11-01 00:00:00')"
    )
    connection.execute("UPDATE analyses SET user_id = 'u1'")
    connection.commit()
    connection.close()

    run_migrations(url)  # 0002 -> 0003
    assert {"resumes", "resume_analyses"} <= _tables(url)
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT user_id, resume_id, resume_filename FROM analyses").fetchall() == [
        ("u1", None, "old.pdf")
    ]
    connection.close()

    # The app works on the upgraded database and new analyses get linked resumes.
    with TestClient(create_app(settings.model_copy(update={"auto_migrate": True}), ai_provider=fake_llm)) as client:
        sign_up(client, "new@example.com")
        res = client.post(
            "/api/analyze",
            files={"resume": ("cv.md", b"# Jane Doe\njane@example.com\n## Experience\n- Built APIs", "text/markdown")},
            data={"jd_text": "jd"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["resume_id"]

    downgrade(url, "0002")
    assert not {"resumes", "resume_analyses"} & _tables(url)
    connection = sqlite3.connect(db_path)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(analyses)")]
    rows = connection.execute("SELECT user_id, resume_filename FROM analyses ORDER BY id").fetchall()
    connection.close()
    assert "resume_id" not in columns
    assert rows[0] == ("u1", "old.pdf")  # legacy history survives the rollback
    assert len(rows) == 2


def test_job_matching_tables_indexes_and_downgrade(tmp_path: Path, fake_llm: FakeLLM) -> None:
    """0004 adds job matching storage; downgrading to 0003 drops only that and keeps earlier history."""

    db_path = tmp_path / "m4.db"
    url = _url(db_path)
    settings = make_settings(tmp_path, database_url=url)
    with TestClient(create_app(settings, ai_provider=fake_llm)) as client:
        sign_up(client, "m4@example.com")
        res = client.post(
            "/api/analyze",
            files={"resume": ("cv.md", b"# Jane Doe\nPython developer", "text/markdown")},
            data={"jd_text": "Requirements: Python"},
        )
        assert res.status_code == 200, res.text

    engine = sa.create_engine(url)
    inspector = sa.inspect(engine)
    assert {"job_descriptions", "job_requirements", "job_matches", "matching_configs", "embedding_cache"} <= set(
        inspector.get_table_names()
    )
    assert {"ix_job_matches_user_id_created_at", "ix_job_matches_resume_id", "ix_job_matches_job_description_id"} <= {
        ix["name"] for ix in inspector.get_indexes("job_matches")
    }
    assert "ix_analyses_job_match_id" in {ix["name"] for ix in inspector.get_indexes("analyses")}
    engine.dispose()

    downgrade(url, "0003")
    tables = _tables(url)
    assert "job_matches" not in tables
    assert "embedding_cache" not in tables
    rows = sqlite3.connect(db_path).execute("SELECT resume_filename, score FROM analyses").fetchall()
    assert rows
    assert rows[0][0] == "cv.md"
    assert sqlite3.connect(db_path).execute("SELECT count(*) FROM resumes").fetchone() == (1,)
    run_migrations(url)
    assert "job_matches" in _tables(url)


def test_rewrite_tables_upgrade_downgrade_and_reupgrade(tmp_path: Path, fake_llm: FakeLLM) -> None:
    """0005 is additive. Downgrading to 0004 removes only rewrite data; re-upgrading restores the schema.

    Backend-agnostic: runs on PostgreSQL when TEST_DATABASE_URL is set, otherwise on SQLite.
    """

    from tests.fixtures.documents import SAMPLE_RESUME_MD

    settings = make_settings(tmp_path)
    url = settings.database_url
    with TestClient(create_app(settings, ai_provider=fake_llm)) as client:
        sign_up(client, "m5@example.com")
        resume = client.post("/api/v1/resumes", files={"file": ("cv.md", SAMPLE_RESUME_MD.encode(), "text/markdown")})
        assert resume.status_code == 201, resume.text
        rewrite = client.post("/api/v1/rewrites", json={"resume_id": resume.json()["id"]})
        assert rewrite.status_code == 201, rewrite.text
        exported = client.post(f"/api/v1/rewrites/{rewrite.json()['id']}/export", json={"format": "docx"})
        assert exported.status_code == 200

    engine = sa.create_engine(url)
    inspector = sa.inspect(engine)
    assert {"resume_rewrites", "resume_rewrite_versions", "resume_rewrite_exports"} <= set(inspector.get_table_names())
    assert {"ix_resume_rewrites_user_id_updated_at", "ix_resume_rewrites_resume_id"} <= {
        ix["name"] for ix in inspector.get_indexes("resume_rewrites")
    }
    assert "uq_resume_rewrite_versions_rewrite_id_number" in {
        c["name"] for c in inspector.get_unique_constraints("resume_rewrite_versions")
    }
    foreign_keys = {
        fk["referred_table"]: fk["options"].get("ondelete") for fk in inspector.get_foreign_keys("resume_rewrites")
    }
    assert foreign_keys == {"users": "CASCADE", "resumes": "CASCADE", "job_descriptions": "SET NULL"}
    engine.dispose()

    downgrade(url, "0004")
    tables = _tables(url)
    assert not {"resume_rewrites", "resume_rewrite_versions", "resume_rewrite_exports"} & tables
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM resumes")).scalar() == 1
        assert connection.execute(sa.text("SELECT count(*) FROM users")).scalar() == 1
    engine.dispose()

    run_migrations(url)
    assert {"resume_rewrites", "resume_rewrite_versions", "resume_rewrite_exports"} <= _tables(url)
    with TestClient(create_app(settings.model_copy(update={"auto_migrate": False}), ai_provider=fake_llm)) as client:
        client.post("/api/v1/auth/login", json={"email": "m5@example.com", "password": "correct horse battery"})
        client.headers["X-CSRF-Token"] = client.get("/api/v1/auth/me").json()["csrf_token"]
        resume_id = client.get("/api/v1/resumes").json()[0]["id"]
        assert client.post("/api/v1/rewrites", json={"resume_id": resume_id}).status_code == 201


def test_0006_detach_and_export_ack_columns_round_trip(tmp_path: Path, fake_llm: FakeLLM) -> None:
    """0006 adds three columns. Downgrading to 0005 drops only them; data in other columns survives.

    Backend-agnostic: runs on PostgreSQL when TEST_DATABASE_URL is set, otherwise on SQLite.
    """

    from tests.fixtures.documents import SAMPLE_JD, SAMPLE_RESUME_MD

    settings = make_settings(tmp_path)
    url = settings.database_url
    with TestClient(create_app(settings, ai_provider=fake_llm)) as client:
        sign_up(client, "m6@example.com")
        resume = client.post("/api/v1/resumes", files={"file": ("cv.md", SAMPLE_RESUME_MD.encode(), "text/markdown")})
        job = client.post("/api/v1/jobs", data={"text": SAMPLE_JD})
        rewrite = client.post("/api/v1/rewrites", json={"resume_id": resume.json()["id"], "job_id": job.json()["id"]})
        assert rewrite.status_code == 201, rewrite.text
        rewrite_id = rewrite.json()["id"]
        assert client.post(f"/api/v1/rewrites/{rewrite_id}/export", json={"format": "docx"}).status_code == 200
        assert client.delete(f"/api/v1/jobs/{job.json()['id']}").status_code == 204

    def columns(table: str) -> set[str]:
        engine = sa.create_engine(url)
        try:
            return {c["name"] for c in sa.inspect(engine).get_columns(table)}
        finally:
            engine.dispose()

    assert "job_detached_at" in columns("resume_rewrites")
    assert {"verification_status", "acknowledged_unverified"} <= columns("resume_rewrite_exports")

    downgrade(url, "0005")
    assert "job_detached_at" not in columns("resume_rewrites")
    assert not {"verification_status", "acknowledged_unverified"} & columns("resume_rewrite_exports")
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM resume_rewrites")).scalar() == 1
        assert connection.execute(sa.text("SELECT count(*) FROM resume_rewrite_exports")).scalar() == 1
    engine.dispose()

    run_migrations(url)
    assert "job_detached_at" in columns("resume_rewrites")
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        row = connection.execute(
            sa.text("SELECT verification_status, acknowledged_unverified FROM resume_rewrite_exports")
        ).one()
        assert row[0] is None  # recorded before the downgrade; the value was dropped with the column
        assert not row[1]  # server default
        assert connection.execute(sa.text("SELECT job_detached_at FROM resume_rewrites")).scalar() is None
    engine.dispose()
    with TestClient(create_app(settings.model_copy(update={"auto_migrate": False}), ai_provider=fake_llm)) as client:
        client.post("/api/v1/auth/login", json={"email": "m6@example.com", "password": "correct horse battery"})
        client.headers["X-CSRF-Token"] = client.get("/api/v1/auth/me").json()["csrf_token"]
        assert client.get(f"/api/v1/rewrites/{rewrite_id}").status_code == 200
        assert client.post(f"/api/v1/rewrites/{rewrite_id}/export", json={"format": "docx"}).status_code == 200
