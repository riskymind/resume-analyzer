"""`python -m app.cli` history assignment: safety rails, backup, verification, rollback."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.application import create_app
from app.core.config import Settings
from tests.conftest import BACKEND_DIR, DEFAULT_PASSWORD, FakeLLM, make_settings, sign_up
from tests.integration.test_migrations import LEGACY_DDL


def _seed_legacy(db_path: Path, count: int) -> None:
    connection = sqlite3.connect(db_path)
    connection.execute(LEGACY_DDL)
    for index in range(1, count + 1):
        connection.execute(
            "INSERT INTO analyses (created_at, resume_filename, jd_source, resume_text, jd_text, score, score_label, "
            "recommendations_json) VALUES (?, ?, 'pasted', 'r', 'j', ?, 'Fair Match', ?)",
            (
                f"2026-11-0{index}T10:00:00+00:00",
                f"old-{index}.pdf",
                40 + index,
                '{"missing_keywords": [], "phrasing_suggestions": [], "skill_gaps": [], "formatting_notes": []}',
            ),
        )
    connection.commit()
    connection.close()


def _owners(db_path: Path) -> dict[int, str | None]:
    connection = sqlite3.connect(db_path)
    try:
        return dict(connection.execute("SELECT id, user_id FROM analyses ORDER BY id").fetchall())
    finally:
        connection.close()


class Recorder:
    def __init__(self, answer: str = "assign") -> None:
        self.lines: list[str] = []
        self.answer = answer
        self.questions: list[str] = []

    def io(self) -> cli.Io:
        def ask(prompt: str) -> str:
            self.questions.append(prompt)
            return self.answer

        return cli.Io(out=self.lines.append, ask=ask)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def legacy(tmp_path: Path, fake_llm: FakeLLM) -> tuple[Settings, Path]:
    db_path = tmp_path / "legacy.db"
    _seed_legacy(db_path, 3)
    settings = make_settings(tmp_path, database_url=f"sqlite:///{db_path.as_posix()}")
    with TestClient(create_app(settings, ai_provider=fake_llm)) as client:  # migrates the legacy DB
        sign_up(client, "owner@example.com")
        sign_up(client, "someone-else@example.com")
    return settings, db_path


def _run(settings: Settings, tmp_path: Path, *args: str, answer: str = "assign") -> tuple[int, Recorder]:
    recorder = Recorder(answer)
    argv = [*args]
    if args and args[0] == "assign-history":
        argv += ["--backup-dir", str(tmp_path / "backups")]
    return cli.main(argv, settings=settings, io=recorder.io()), recorder


def test_list_unowned(legacy: tuple[Settings, Path], tmp_path: Path) -> None:
    settings, _ = legacy
    code, out = _run(settings, tmp_path, "list-unowned")
    assert code == 0
    assert "3 unowned analyses" in out.text
    assert "old-2.pdf" in out.text


def test_dry_run_changes_nothing(legacy: tuple[Settings, Path], tmp_path: Path) -> None:
    settings, db_path = legacy
    code, out = _run(settings, tmp_path, "assign-history", "--email", "owner@example.com", "--dry-run")
    assert code == 0
    assert "Dry run" in out.text
    assert set(_owners(db_path).values()) == {None}
    assert not (tmp_path / "backups").exists()


def test_requires_typed_confirmation(legacy: tuple[Settings, Path], tmp_path: Path) -> None:
    settings, db_path = legacy
    code, out = _run(settings, tmp_path, "assign-history", "--email", "owner@example.com", answer="yes")
    assert code == 2
    assert out.questions == ["Type 'assign' to continue: "]
    assert set(_owners(db_path).values()) == {None}


def test_unknown_account_is_an_error(legacy: tuple[Settings, Path], tmp_path: Path) -> None:
    settings, db_path = legacy
    code, out = _run(settings, tmp_path, "assign-history", "--email", "ghost@example.com")
    assert code == 1
    assert "Register it in the app first" in out.text
    assert set(_owners(db_path).values()) == {None}


def test_assign_backup_verify_and_rollback(legacy: tuple[Settings, Path], tmp_path: Path, fake_llm: FakeLLM) -> None:
    settings, db_path = legacy

    code, out = _run(settings, tmp_path, "assign-history", "--email", "OWNER@example.com")
    assert code == 0, out.text
    assert "Verified: 3 analyses now belong to owner@example.com." in out.text

    owners = _owners(db_path)
    assert len(set(owners.values())) == 1
    owner_id = next(iter(owners.values()))
    assert owner_id is not None

    backups = sorted((tmp_path / "backups").glob("resume_analyzer-*.db"))
    manifests = sorted((tmp_path / "backups").glob("history-assignment-*.json"))
    assert len(backups) == 1
    assert len(manifests) == 1
    # The backup is a complete, readable copy taken before the change.
    assert set(_owners(backups[0]).values()) == {None}
    manifest = json.loads(manifests[0].read_text())
    assert manifest["analysis_ids"] == [1, 2, 3]
    assert manifest["user_id"] == owner_id
    assert "password" not in manifests[0].read_text().lower()

    # The owner now sees the history through the API; another user does not.
    with TestClient(create_app(settings, ai_provider=fake_llm)) as client:
        client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": DEFAULT_PASSWORD})
        assert [item["resume_filename"] for item in client.get("/api/analyses").json()] == [
            "old-3.pdf",
            "old-2.pdf",
            "old-1.pdf",
        ]
    with TestClient(create_app(settings, ai_provider=fake_llm)) as other:
        other.post("/api/v1/auth/login", json={"email": "someone-else@example.com", "password": DEFAULT_PASSWORD})
        assert other.get("/api/analyses").json() == []

    code, out = _run(
        settings, tmp_path, "rollback-history-assignment", "--manifest", str(manifests[0]), answer="rollback"
    )
    assert code == 0, out.text
    assert set(_owners(db_path).values()) == {None}


def test_selected_ids_only(legacy: tuple[Settings, Path], tmp_path: Path) -> None:
    settings, db_path = legacy
    code, _ = _run(settings, tmp_path, "assign-history", "--email", "owner@example.com", "--ids", "2")
    assert code == 0
    owners = _owners(db_path)
    assert owners[1] is None
    assert owners[3] is None
    assert owners[2] is not None


def test_never_reassigns_owned_rows(legacy: tuple[Settings, Path], tmp_path: Path) -> None:
    settings, db_path = legacy
    _run(settings, tmp_path, "assign-history", "--email", "owner@example.com", "--ids", "1")
    first_owner = _owners(db_path)[1]

    code, out = _run(settings, tmp_path, "assign-history", "--email", "someone-else@example.com", "--ids", "1,2")
    assert code == 1
    assert "already have an owner" in out.text
    owners = _owners(db_path)
    assert owners[1] == first_owner
    assert owners[2] is None  # nothing partially applied


def test_rollback_does_not_touch_rows_reassigned_since(legacy: tuple[Settings, Path], tmp_path: Path) -> None:
    settings, db_path = legacy
    _run(settings, tmp_path, "assign-history", "--email", "owner@example.com", "--ids", "1")
    manifest = next((tmp_path / "backups").glob("history-assignment-*.json"))
    connection = sqlite3.connect(db_path)
    connection.execute("UPDATE analyses SET user_id = (SELECT id FROM users WHERE email = 'someone-else@example.com')")
    connection.commit()
    connection.close()

    code, _ = _run(settings, tmp_path, "rollback-history-assignment", "--manifest", str(manifest), "--yes")
    assert code == 0
    assert None not in _owners(db_path).values()


def test_module_entry_point_runs_as_subprocess(legacy: tuple[Settings, Path]) -> None:
    _, db_path = legacy
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "GEMINI_API_KEY": "",
        "APP_ENV": "development",
    }
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "list-unowned"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "3 unowned analyses" in result.stdout
