"""Cross-user data isolation for every endpoint that touches user-owned data."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories import analyses as analyses_repo
from tests.conftest import sign_up

ALICE_MARKER = "alice-private-resume.md"


def _analyze(client: TestClient, filename: str) -> dict[str, Any]:
    res = client.post(
        "/api/analyze",
        files={"resume": (filename, b"# Private resume\nPython", "text/markdown")},
        data={"jd_text": "Python developer"},
    )
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


@pytest.fixture
def alice(new_client: Callable[[], TestClient]) -> TestClient:
    client = new_client()
    sign_up(client, "alice@example.com")
    return client


@pytest.fixture
def bob(new_client: Callable[[], TestClient]) -> TestClient:
    client = new_client()
    sign_up(client, "bob@example.com")
    return client


def test_history_lists_only_own_analyses(alice: TestClient, bob: TestClient) -> None:
    alice_record = _analyze(alice, ALICE_MARKER)
    bob_record = _analyze(bob, "bob.md")

    assert [item["id"] for item in alice.get("/api/analyses").json()] == [alice_record["id"]]
    bob_listing = bob.get("/api/analyses")
    assert [item["id"] for item in bob_listing.json()] == [bob_record["id"]]
    assert ALICE_MARKER not in bob_listing.text


def test_other_users_analysis_is_not_found_and_not_leaked(alice: TestClient, bob: TestClient) -> None:
    alice_record = _analyze(alice, ALICE_MARKER)
    res = bob.get(f"/api/analyses/{alice_record['id']}")
    assert res.status_code == 404
    assert ALICE_MARKER not in res.text
    # Same response as for an id that does not exist at all (no existence oracle).
    missing = bob.get("/api/analyses/987654")
    assert res.json()["error"]["code"] == missing.json()["error"]["code"] == "not_found"


def test_enumerating_ids_reveals_nothing(alice: TestClient, bob: TestClient) -> None:
    alice_record = _analyze(alice, ALICE_MARKER)
    for candidate in range(1, alice_record["id"] + 3):
        res = bob.get(f"/api/analyses/{candidate}")
        assert res.status_code == 404
        assert ALICE_MARKER not in res.text


def test_new_analysis_is_owned_by_creator(alice: TestClient, bob: TestClient) -> None:
    record = _analyze(bob, "bob.md")
    assert bob.get(f"/api/analyses/{record['id']}").status_code == 200
    assert alice.get(f"/api/analyses/{record['id']}").status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/analyses"),
        ("GET", "/api/analyses/1"),
        ("POST", "/api/analyze"),
        ("GET", "/api/v1/auth/me"),
        ("DELETE", "/api/v1/auth/me"),
    ],
)
def test_anonymous_requests_are_rejected(alice: TestClient, anon_client: TestClient, method: str, path: str) -> None:
    _analyze(alice, ALICE_MARKER)
    if method == "POST":
        res = anon_client.post(path, files={"resume": ("r.md", b"# x", "text/markdown")}, data={"jd_text": "x"})
    elif method == "DELETE":
        res = anon_client.request("DELETE", path, json={"password": "irrelevant", "confirmation": "delete my account"})
    else:
        res = anon_client.request(method, path)
    assert res.status_code == 401
    assert ALICE_MARKER not in res.text


def test_account_deletion_cannot_target_another_user(alice: TestClient, bob: TestClient) -> None:
    """DELETE /auth/me always acts on the caller; there is no user id to tamper with."""

    _analyze(alice, ALICE_MARKER)
    res = bob.request(
        "DELETE",
        "/api/v1/auth/me",
        json={"password": "correct horse battery", "confirmation": "delete my account"},
    )
    assert res.status_code == 204
    assert len(alice.get("/api/analyses").json()) == 1
    assert alice.get("/api/v1/auth/me").status_code == 200


def test_repository_layer_enforces_ownership(app: FastAPI, alice: TestClient, bob: TestClient) -> None:
    """Defence in depth: the scoping lives in SQL, not in the route handlers."""

    alice_record = _analyze(alice, ALICE_MARKER)
    bob_id = bob.get("/api/v1/auth/me").json()["user"]["id"]
    alice_id = alice.get("/api/v1/auth/me").json()["user"]["id"]
    with app.state.db.session() as db:
        assert analyses_repo.get(db, user_id=bob_id, analysis_id=alice_record["id"]) is None
        assert analyses_repo.get(db, user_id=alice_id, analysis_id=alice_record["id"]) is not None
        assert analyses_repo.list_recent(db, user_id=bob_id) == []
