"""Registration, login, logout, sessions, cookies and CSRF."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.application import create_app
from app.db.models import AuthSession, User
from app.db.types import utcnow
from app.services import auth as auth_service
from tests.conftest import DEFAULT_PASSWORD, FakeLLM, make_settings, sign_up

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
COOKIE = "ra_session"


def _session_count(app: FastAPI) -> int:
    with app.state.db.session() as db:
        return int(db.scalar(select(func.count()).select_from(AuthSession)) or 0)


def _analyze(client: TestClient, **headers: str):
    return client.post(
        "/api/analyze",
        files={"resume": ("r.md", b"# Jane\nPython", "text/markdown")},
        data={"jd_text": "Python developer"},
        headers=headers,
    )


class TestRegistration:
    def test_register_signs_in_and_sets_hardened_cookie(self, anon_client: TestClient) -> None:
        res = anon_client.post(REGISTER, json={"email": "Jane@Example.com ", "password": DEFAULT_PASSWORD})
        assert res.status_code == 201
        body = res.json()
        assert body["user"]["email"] == "jane@example.com"
        assert len(body["csrf_token"]) >= 43
        cookie = res.headers["set-cookie"]
        assert cookie.startswith(f"{COOKIE}=")
        for attribute in ("HttpOnly", "SameSite=lax", "Path=/", "Max-Age=604800"):
            assert attribute.lower() in cookie.lower()
        assert "domain=" not in cookie.lower()
        assert anon_client.get(ME).json()["user"]["email"] == "jane@example.com"

    def test_password_is_stored_as_argon2id(self, app: FastAPI, client: TestClient) -> None:
        with app.state.db.session() as db:
            user = db.scalar(select(User))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert DEFAULT_PASSWORD not in user.password_hash

    @pytest.mark.parametrize(
        ("email", "password", "code"),
        [
            ("not-an-email", DEFAULT_PASSWORD, "invalid_email"),
            ("a@b", DEFAULT_PASSWORD, "invalid_email"),
            ("jane@example.com", "short", "weak_password"),
            ("jane@example.com", "JANE@example.com", "weak_password"),
        ],
    )
    def test_invalid_registration(self, anon_client: TestClient, email: str, password: str, code: str) -> None:
        res = anon_client.post(REGISTER, json={"email": email, "password": password})
        assert res.status_code == 400
        assert res.json()["error"]["code"] == code

    def test_duplicate_email_is_case_insensitive(
        self, anon_client: TestClient, new_client: Callable[[], TestClient]
    ) -> None:
        sign_up(anon_client, "jane@example.com")
        res = new_client().post(REGISTER, json={"email": "JANE@example.com", "password": DEFAULT_PASSWORD})
        assert res.status_code == 409

    def test_validation_errors_never_echo_the_password(self, anon_client: TestClient) -> None:
        res = anon_client.post(REGISTER, json={"email": "x@example.com", "password": "p" * 2000})
        assert res.status_code == 422
        assert "ppppp" not in res.text


class TestLogin:
    def test_login_success(self, client: TestClient, anon_client: TestClient) -> None:
        res = anon_client.post(LOGIN, json={"email": "OWNER@example.com", "password": DEFAULT_PASSWORD})
        assert res.status_code == 200
        assert res.json()["user"]["email"] == "owner@example.com"
        assert anon_client.get(ME).status_code == 200

    @pytest.mark.parametrize(
        ("email", "password"), [("owner@example.com", "wrong password!"), ("nobody@example.com", DEFAULT_PASSWORD)]
    )
    def test_failed_login_is_generic(
        self, client: TestClient, anon_client: TestClient, email: str, password: str
    ) -> None:
        res = anon_client.post(LOGIN, json={"email": email, "password": password})
        assert res.status_code == 401
        assert res.json()["error"] == {
            "code": "invalid_credentials",
            "message": "Invalid email or password.",
            "request_id": res.headers["x-request-id"],
        }
        assert "set-cookie" not in res.headers

    def test_login_rotates_session(self, app: FastAPI, client: TestClient) -> None:
        old_token = client.cookies[COOKIE]
        old_csrf = client.headers["X-CSRF-Token"]
        res = client.post(LOGIN, json={"email": "owner@example.com", "password": DEFAULT_PASSWORD})
        new_token = client.cookies[COOKIE]
        assert new_token != old_token
        assert res.json()["csrf_token"] != old_csrf
        assert _session_count(app) == 1  # the presented session was revoked, not left behind

        replay = TestClient(app)
        replay.cookies.set(COOKIE, old_token)
        assert replay.get(ME).status_code == 401

    def test_preset_session_id_cannot_be_fixated(self, client: TestClient, anon_client: TestClient) -> None:
        res = anon_client.post(
            LOGIN,
            json={"email": "owner@example.com", "password": DEFAULT_PASSWORD},
            headers={"Cookie": f"{COOKIE}=attacker-chosen-value"},
        )
        assert res.status_code == 200
        issued = res.cookies[COOKIE]
        assert issued != "attacker-chosen-value"
        assert len(issued) >= 43

    def test_login_rehashes_outdated_password_hash(self, tmp_path: Path, fake_llm: FakeLLM) -> None:
        settings_v1 = make_settings(tmp_path)
        with TestClient(create_app(settings_v1, ai_provider=fake_llm)) as first:
            sign_up(first)
        # Same database, stronger hashing parameters (make_settings would reset a Postgres schema).
        settings_v2 = settings_v1.model_copy(update={"password_hash_memory_kib": 2048})
        app = create_app(settings_v2, ai_provider=fake_llm)
        with TestClient(app) as second:
            second.post(LOGIN, json={"email": "owner@example.com", "password": DEFAULT_PASSWORD})
            with app.state.db.session() as db:
                user = db.scalar(select(User))
        assert user is not None
        assert "m=2048" in user.password_hash


class TestSessions:
    def test_only_token_hash_is_stored(self, app: FastAPI, client: TestClient) -> None:
        token = client.cookies[COOKIE]
        with app.state.db.session() as db:
            stored = db.scalar(select(AuthSession))
        assert stored is not None
        assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in (stored.token_hash, stored.csrf_token, stored.id)

    def test_me_requires_session(self, anon_client: TestClient) -> None:
        res = anon_client.get(ME)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "not_authenticated"

    def test_forged_cookie_rejected(self, anon_client: TestClient) -> None:
        anon_client.cookies.set(COOKIE, "forged")
        assert anon_client.get(ME).status_code == 401

    def test_absolute_expiry(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        future = utcnow() + timedelta(hours=168, seconds=1)
        monkeypatch.setattr(auth_service, "_now", lambda: future)
        assert client.get(ME).status_code == 401

    def test_idle_timeout(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        later = utcnow() + timedelta(hours=24, seconds=1)
        monkeypatch.setattr(auth_service, "_now", lambda: later)
        assert client.get(ME).status_code == 401

    def test_activity_extends_idle_window(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        start = utcnow()
        monkeypatch.setattr(auth_service, "_now", lambda: start + timedelta(hours=20))
        assert client.get(ME).status_code == 200  # refreshes last_seen_at
        monkeypatch.setattr(auth_service, "_now", lambda: start + timedelta(hours=40))
        assert client.get(ME).status_code == 200

    def test_expired_session_is_deleted(
        self, app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(auth_service, "_now", lambda: utcnow() + timedelta(days=30))
        client.get(ME)
        assert _session_count(app) == 0

    def test_session_survives_backend_restart(self, tmp_path: Path, fake_llm: FakeLLM) -> None:
        settings = make_settings(tmp_path)
        with TestClient(create_app(settings, ai_provider=fake_llm)) as before:
            sign_up(before)
            token = before.cookies[COOKIE]
            csrf = before.headers["X-CSRF-Token"]

        with TestClient(create_app(settings, ai_provider=fake_llm)) as after:  # new process, same database
            after.cookies.set(COOKIE, token)
            me = after.get(ME)
            assert me.status_code == 200
            assert me.json()["csrf_token"] == csrf
            assert _analyze(after, **{"X-CSRF-Token": csrf}).status_code == 200

    def test_secure_cookie_configuration(self, tmp_path: Path, fake_llm: FakeLLM) -> None:
        settings = make_settings(tmp_path, cookie_secure=True)
        with TestClient(create_app(settings, ai_provider=fake_llm), base_url="https://testserver") as secure_client:
            res = secure_client.post(REGISTER, json={"email": "s@example.com", "password": DEFAULT_PASSWORD})
            cookie = res.headers["set-cookie"]
            assert cookie.startswith("__Host-ra_session=")
            assert "secure" in cookie.lower()
            assert "domain=" not in cookie.lower()
            assert secure_client.get(ME).status_code == 200


class TestLogout:
    def test_logout_revokes_session_and_clears_cookie(self, app: FastAPI, client: TestClient) -> None:
        token = client.cookies[COOKIE]
        res = client.post(LOGOUT)
        assert res.status_code == 204
        assert 'ra_session=""' in res.headers["set-cookie"] or "Max-Age=0" in res.headers["set-cookie"]
        assert _session_count(app) == 0
        replay = TestClient(app)
        replay.cookies.set(COOKIE, token)
        assert replay.get(ME).status_code == 401

    def test_logout_requires_csrf(self, app: FastAPI, client: TestClient) -> None:
        del client.headers["X-CSRF-Token"]
        res = client.post(LOGOUT)
        assert res.status_code == 403
        assert _session_count(app) == 1

    def test_logout_without_session_is_harmless(self, anon_client: TestClient) -> None:
        assert anon_client.post(LOGOUT).status_code == 204

    def test_logout_only_ends_current_device(self, app: FastAPI, client: TestClient, anon_client: TestClient) -> None:
        anon_client.post(LOGIN, json={"email": "owner@example.com", "password": DEFAULT_PASSWORD})
        client.post(LOGOUT)
        assert anon_client.get(ME).status_code == 200


class TestCsrf:
    def test_missing_token_rejected(self, client: TestClient) -> None:
        del client.headers["X-CSRF-Token"]
        res = _analyze(client)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "csrf_failed"

    def test_wrong_token_rejected(self, client: TestClient) -> None:
        assert _analyze(client, **{"X-CSRF-Token": "guess"}).status_code == 403

    def test_token_from_another_session_rejected(
        self, client: TestClient, new_client: Callable[[], TestClient]
    ) -> None:
        other = new_client()
        other_csrf = sign_up(other, "other@example.com")["csrf_token"]
        assert _analyze(client, **{"X-CSRF-Token": other_csrf}).status_code == 403

    @pytest.mark.parametrize("origin", ["https://evil.example.com", "null", "http://localhost:5174"])
    def test_untrusted_origin_rejected_even_with_valid_token(self, client: TestClient, origin: str) -> None:
        res = _analyze(client, Origin=origin)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "origin_not_allowed"

    def test_untrusted_referer_rejected(self, client: TestClient) -> None:
        assert _analyze(client, Referer="https://evil.example.com/attack.html").status_code == 403

    def test_trusted_frontend_origin_accepted(self, client: TestClient) -> None:
        assert _analyze(client, Origin="http://localhost:5173").status_code == 200

    def test_same_origin_accepted(self, client: TestClient) -> None:
        assert _analyze(client, Origin="http://testserver").status_code == 200

    @pytest.mark.parametrize("path", [LOGIN, REGISTER])
    def test_login_csrf_blocked_by_origin_check(self, client: TestClient, anon_client: TestClient, path: str) -> None:
        res = anon_client.post(
            path,
            json={"email": "owner@example.com", "password": DEFAULT_PASSWORD},
            headers={"Origin": "https://evil.example.com"},
        )
        assert res.status_code == 403
        assert "set-cookie" not in res.headers

    def test_safe_methods_do_not_need_token(self, client: TestClient) -> None:
        del client.headers["X-CSRF-Token"]
        assert client.get("/api/analyses").status_code == 200
        assert client.get(ME).status_code == 200
