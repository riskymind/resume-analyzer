"""Account deletion: confirmation, CSRF, complete transactional cleanup, no orphans."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import delete, func, select, text

from app.db.models import Analysis, AuthSession, Base, User
from app.services import auth as auth_service
from tests.conftest import DEFAULT_PASSWORD, sign_up

ME = "/api/v1/auth/me"
CONFIRM = {"password": DEFAULT_PASSWORD, "confirmation": "delete my account"}


def _analyze(client: TestClient) -> None:
    res = client.post(
        "/api/analyze",
        files={"resume": ("r.md", b"# Resume text", "text/markdown")},
        data={"jd_text": "JD text"},
    )
    assert res.status_code == 200, res.text


def _delete(client: TestClient, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Response:
    return client.request("DELETE", ME, json=CONFIRM if body is None else body, headers=headers)


def _owned_row_counts(app: FastAPI, user_id: str) -> dict[str, int]:
    """Count rows referencing ``user_id`` in every table that has a user_id column."""

    counts: dict[str, int] = {}
    with app.state.db.session() as db:
        for table in Base.metadata.sorted_tables:
            if "user_id" in table.c:
                counts[table.name] = int(
                    db.scalar(select(func.count()).select_from(table).where(table.c.user_id == user_id)) or 0
                )
        counts["users"] = int(db.scalar(select(func.count()).select_from(User).where(User.id == user_id)) or 0)
    return counts


@pytest.fixture
def owner_id(client: TestClient) -> str:
    user_id: str = client.get(ME).json()["user"]["id"]
    return user_id


def test_deletes_user_sessions_and_all_owned_data(
    app: FastAPI, client: TestClient, new_client: Callable[[], TestClient], owner_id: str
) -> None:
    _analyze(client)
    _analyze(client)
    second_device = new_client()
    second_device.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": DEFAULT_PASSWORD})
    assert _owned_row_counts(app, owner_id) == {
        "sessions": 2,
        "analyses": 2,
        "resume_analyses": 2,
        "resumes": 2,
        "job_descriptions": 2,
        "job_requirements": 0,  # "JD text" contains no verifiable requirements
        "job_matches": 2,
        "embedding_cache": 0,
        "resume_rewrites": 0,
        "resume_rewrite_versions": 0,
        "resume_rewrite_exports": 0,
        "users": 1,
    }

    res = _delete(client)
    assert res.status_code == 204
    assert "max-age=0" in res.headers["set-cookie"].lower()

    assert _owned_row_counts(app, owner_id) == {
        "sessions": 0,
        "analyses": 0,
        "resume_analyses": 0,
        "resumes": 0,
        "job_descriptions": 0,
        "job_requirements": 0,
        "job_matches": 0,
        "embedding_cache": 0,
        "resume_rewrites": 0,
        "resume_rewrite_versions": 0,
        "resume_rewrite_exports": 0,
        "users": 0,
    }
    assert client.get(ME).status_code == 401
    assert second_device.get(ME).status_code == 401  # every device is signed out


def test_resume_text_is_gone_from_database(app: FastAPI, client: TestClient) -> None:
    client.post(
        "/api/analyze",
        files={"resume": ("r.md", b"# UNIQUE-RESUME-CONTENT-123", "text/markdown")},
        data={"jd_text": "UNIQUE-JD-CONTENT-456"},
    )
    _delete(client)
    with app.state.db.session() as db:
        rows = db.execute(text("SELECT resume_text, jd_text FROM analyses")).fetchall()
    assert all("UNIQUE-RESUME-CONTENT-123" not in row[0] and "UNIQUE-JD-CONTENT-456" not in row[1] for row in rows)


def test_other_users_are_untouched(app: FastAPI, client: TestClient, new_client: Callable[[], TestClient]) -> None:
    other = new_client()
    sign_up(other, "other@example.com")
    _analyze(other)
    other_id = other.get(ME).json()["user"]["id"]
    _analyze(client)

    assert _delete(client).status_code == 204
    assert _owned_row_counts(app, other_id) == {
        "sessions": 1,
        "analyses": 1,
        "resume_analyses": 1,
        "resumes": 1,
        "job_descriptions": 1,
        "job_requirements": 0,
        "job_matches": 1,
        "embedding_cache": 0,
        "resume_rewrites": 0,
        "resume_rewrite_versions": 0,
        "resume_rewrite_exports": 0,
        "users": 1,
    }
    assert len(other.get("/api/analyses").json()) == 1


def test_email_can_be_registered_again(client: TestClient, new_client: Callable[[], TestClient]) -> None:
    _delete(client)
    fresh = new_client()
    sign_up(fresh, "owner@example.com")
    assert fresh.get("/api/analyses").json() == []


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"password": DEFAULT_PASSWORD}, 422),
        ({"password": DEFAULT_PASSWORD, "confirmation": "yes"}, 422),
        ({"password": DEFAULT_PASSWORD, "confirmation": "DELETE MY ACCOUNT"}, 422),
        ({"password": "wrong password!", "confirmation": "delete my account"}, 403),
    ],
    ids=["no-confirmation", "wrong-phrase", "wrong-case", "wrong-password"],
)
def test_requires_explicit_confirmation_and_password(
    app: FastAPI, client: TestClient, owner_id: str, body: dict[str, Any], status: int
) -> None:
    _analyze(client)
    assert _delete(client, body).status_code == status
    assert _owned_row_counts(app, owner_id) == {
        "sessions": 1,
        "analyses": 1,
        "resume_analyses": 1,
        "resumes": 1,
        "job_descriptions": 1,
        "job_requirements": 0,
        "job_matches": 1,
        "embedding_cache": 0,
        "resume_rewrites": 0,
        "resume_rewrite_versions": 0,
        "resume_rewrite_exports": 0,
        "users": 1,
    }


def test_requires_csrf(app: FastAPI, client: TestClient, owner_id: str) -> None:
    del client.headers["X-CSRF-Token"]
    assert _delete(client).status_code == 403
    assert _owned_row_counts(app, owner_id)["users"] == 1


def test_cross_site_origin_rejected(app: FastAPI, client: TestClient, owner_id: str) -> None:
    assert _delete(client, headers={"Origin": "https://evil.example.com"}).status_code == 403
    assert _owned_row_counts(app, owner_id)["users"] == 1


def test_deletion_is_atomic(app: FastAPI, client: TestClient, owner_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure after the deletes have run must roll everything back."""

    _analyze(client)
    original_info = auth_service.logger.info

    def fail_on_completion(message: str, *args: Any, **kwargs: Any) -> None:
        if message == "account_deleted":
            raise RuntimeError("simulated crash after deletes")
        original_info(message, *args, **kwargs)

    monkeypatch.setattr(auth_service.logger, "info", fail_on_completion)
    with TestClient(app, raise_server_exceptions=False) as crashing:
        crashing.cookies.update(client.cookies)
        res = _delete(crashing, headers={"X-CSRF-Token": client.headers["X-CSRF-Token"]})
    assert res.status_code == 500
    assert _owned_row_counts(app, owner_id) == {
        "sessions": 1,
        "analyses": 1,
        "resume_analyses": 1,
        "resumes": 1,
        "job_descriptions": 1,
        "job_requirements": 0,
        "job_matches": 1,
        "embedding_cache": 0,
        "resume_rewrites": 0,
        "resume_rewrite_versions": 0,
        "resume_rewrite_exports": 0,
        "users": 1,
    }


def test_database_cascade_also_covers_owned_rows(app: FastAPI, client: TestClient, owner_id: str) -> None:
    """Second line of defence: FK ON DELETE CASCADE removes rows even outside the service."""

    _analyze(client)
    with app.state.db.session() as db, db.begin():
        db.execute(delete(User).where(User.id == owner_id))
    with app.state.db.session() as db:
        assert db.scalar(select(func.count()).select_from(Analysis).where(Analysis.user_id == owner_id)) == 0
        assert db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == owner_id)) == 0
