"""Login, registration and AI rate limits (database-backed, shared across instances)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select

from app.application import create_app
from app.core.config import Settings
from app.core.errors import RateLimitedError
from app.db.models import RateLimitBucket
from app.services.rate_limit import RateLimiter
from tests.conftest import DEFAULT_PASSWORD, FakeLLM, make_settings, sign_up

LOGIN = "/api/v1/auth/login"
REGISTER = "/api/v1/auth/register"

LIMITS = {
    "login_max_attempts_per_ip": 6,
    "login_max_attempts_per_email": 3,
    "register_max_per_ip": 3,
    "ai_max_requests_per_minute": 2,
    "ai_max_requests_per_day": 3,
}


@pytest.fixture
def limited_settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path, **LIMITS)


@pytest.fixture
def limited_app(limited_settings: Settings, fake_llm: FakeLLM) -> Iterator[FastAPI]:
    app = create_app(limited_settings, ai_provider=fake_llm)
    with TestClient(app):
        yield app


WRONG_PASSWORD = "wrong password!"


def _login(client: TestClient, email: str = "owner@example.com", password: str = WRONG_PASSWORD) -> Response:
    return client.post(LOGIN, json={"email": email, "password": password})


def _assert_429(res: Response) -> None:
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "rate_limited"
    assert int(res.headers["retry-after"]) >= 1


def _analyze(client: TestClient) -> Response:
    return client.post(
        "/api/analyze",
        files={"resume": ("r.md", b"# Jane\nPython", "text/markdown")},
        data={"jd_text": "Python dev"},
    )


class TestLoginLimits:
    def test_per_email_limit_blocks_even_correct_password(self, limited_app: FastAPI) -> None:
        with TestClient(limited_app) as client:
            sign_up(client)
            for _ in range(3):
                assert _login(client).status_code == 401
            _assert_429(_login(client, password=DEFAULT_PASSWORD))

    def test_per_email_limit_is_case_insensitive(self, limited_app: FastAPI) -> None:
        with TestClient(limited_app) as client:
            for email in ("a@example.com", "A@example.com", "a@EXAMPLE.com"):
                assert _login(client, email=email).status_code == 401
            _assert_429(_login(client, email="A@Example.Com"))

    def test_per_ip_limit_across_emails(self, limited_app: FastAPI) -> None:
        with TestClient(limited_app) as client:
            for index in range(6):
                assert _login(client, email=f"user{index}@example.com").status_code == 401
            _assert_429(_login(client, email="fresh@example.com"))

    def test_limit_is_shared_between_instances(self, limited_settings: Settings, fake_llm: FakeLLM) -> None:
        """Two app instances on one database behave like two workers/instances."""

        first = create_app(limited_settings, ai_provider=fake_llm)
        second = create_app(limited_settings, ai_provider=fake_llm)
        with TestClient(first) as one, TestClient(second) as two:
            assert _login(one).status_code == 401
            assert _login(two).status_code == 401
            assert _login(one).status_code == 401
            _assert_429(_login(two))


class TestRegistrationLimit:
    def test_register_per_ip(self, limited_app: FastAPI) -> None:
        with TestClient(limited_app) as client:
            for index in range(3):
                res = client.post(REGISTER, json={"email": f"u{index}@example.com", "password": DEFAULT_PASSWORD})
                assert res.status_code == 201
            _assert_429(client.post(REGISTER, json={"email": "u9@example.com", "password": DEFAULT_PASSWORD}))


class TestAiLimits:
    def test_per_minute_limit_stops_before_calling_ai(self, limited_app: FastAPI, fake_llm: FakeLLM) -> None:
        with TestClient(limited_app) as client:
            sign_up(client)
            assert _analyze(client).status_code == 200
            assert _analyze(client).status_code == 200
            calls_before = len(fake_llm.prompts)
            _assert_429(_analyze(client))
            assert len(fake_llm.prompts) == calls_before

    def test_limits_are_per_user(self, limited_app: FastAPI) -> None:
        with TestClient(limited_app) as alice, TestClient(limited_app) as bob:
            sign_up(alice, "alice@example.com")
            sign_up(bob, "bob@example.com")
            _analyze(alice)
            _analyze(alice)
            _assert_429(_analyze(alice))
            assert _analyze(bob).status_code == 200

    def test_daily_quota(self, limited_settings: Settings, fake_llm: FakeLLM) -> None:
        settings = limited_settings.model_copy(update={"ai_max_requests_per_minute": 100})
        app = create_app(settings, ai_provider=fake_llm)
        with TestClient(app) as client:
            sign_up(client)
            for _ in range(3):
                assert _analyze(client).status_code == 200
            res = _analyze(client)
            _assert_429(res)
            assert "today" in res.json()["detail"]

    def test_invalid_upload_does_not_consume_ai_quota(self, limited_app: FastAPI) -> None:
        with TestClient(limited_app) as client:
            sign_up(client)
            for _ in range(5):
                bad = client.post(
                    "/api/analyze",
                    files={"resume": ("r.exe", b"MZ", "application/octet-stream")},
                    data={"jd_text": "x"},
                )
                assert bad.status_code == 400
            assert _analyze(client).status_code == 200


class TestLimiterMechanics:
    def test_window_resets(self, limited_app: FastAPI) -> None:
        now = [1_000_000.0]
        limiter = RateLimiter(limited_app.state.db, clock=lambda: now[0])
        for _ in range(2):
            limiter.hit("t", "id", limit=2, window_seconds=60, message="slow down")
        with pytest.raises(RateLimitedError) as exc_info:
            limiter.hit("t", "id", limit=2, window_seconds=60, message="slow down")
        assert 1 <= exc_info.value.retry_after_seconds <= 60
        now[0] += 60
        assert limiter.hit("t", "id", limit=2, window_seconds=60, message="slow down") == 1

    def test_concurrent_hits_are_counted_exactly(self, limited_app: FastAPI) -> None:
        limiter = RateLimiter(limited_app.state.db, clock=lambda: 2_000_000.0)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                for _ in range(10):
                    limiter.hit("race", "id", limit=10_000, window_seconds=60, message="x")
            except BaseException as exc:  # pragma: no cover - surfaced by the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert limiter.hit("race", "id", limit=10_000, window_seconds=60, message="x") == 81

    def test_identifiers_are_not_stored_in_plaintext(self, limited_app: FastAPI) -> None:
        with TestClient(limited_app) as client:
            _login(client, email="private.person@example.com")
        with limited_app.state.db.session() as db:
            keys = list(db.scalars(select(RateLimitBucket.key)))
        assert keys
        assert all(len(key) == 64 and "@" not in key and "testclient" not in key for key in keys)

    def test_purge_removes_expired_buckets(self, limited_app: FastAPI) -> None:
        now = [3_000_000.0]
        limiter = RateLimiter(limited_app.state.db, clock=lambda: now[0])
        limiter.hit("p", "id", limit=5, window_seconds=60, message="x")
        now[0] += 3600
        limiter.purge_expired()
        with limited_app.state.db.session() as db:
            assert list(db.scalars(select(RateLimitBucket).where(RateLimitBucket.window_start < 3_000_100))) == []
