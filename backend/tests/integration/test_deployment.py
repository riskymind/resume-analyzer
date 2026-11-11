"""Deployment plumbing (Milestone 8): proxy access key, cache headers, operator CLI, locked migrations."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import cli
from app.application import create_app
from app.core.config import Settings
from app.db.migrate import current_revision, head_revision, run_migrations_exclusively
from tests.conftest import BACKEND_DIR, TEST_DATABASE_URL, FakeLLM, make_settings, sign_up

ACCESS_KEY = "k" * 40
HEADER = "X-Backend-Access-Key"


class RecordingIo(cli.Io):
    def __init__(self) -> None:
        self.lines: list[str] = []
        super().__init__(out=self.lines.append, ask=lambda _prompt: "")

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def keyed_client(tmp_path: Path, fake_llm: FakeLLM) -> Iterator[TestClient]:
    app = create_app(make_settings(tmp_path, backend_access_key=ACCESS_KEY), ai_provider=fake_llm)
    with TestClient(app) as test_client:
        yield test_client


class TestBackendAccessKey:
    def test_liveness_is_the_only_path_without_a_key(self, keyed_client: TestClient) -> None:
        assert keyed_client.get("/api/v1/health").status_code == 200
        # The legacy alias, readiness, docs and unknown paths all need the key.
        for path in ("/api/health", "/api/v1/health/ready", "/api/docs", "/api/v1/nope", "/api/v1/health/"):
            assert keyed_client.get(path).status_code == 403, path

    @pytest.mark.parametrize("headers", [{}, {HEADER: "wrong"}, {HEADER: ACCESS_KEY[:-1]}, {HEADER: ACCESS_KEY + "x"}])
    def test_missing_or_wrong_key_is_refused_before_routing(
        self, keyed_client: TestClient, headers: dict[str, str]
    ) -> None:
        targets = [("GET", "/api/v1/health/ready"), ("GET", "/api/v1/auth/me"), ("POST", "/api/v1/auth/login")]
        for method, path in targets:
            res = keyed_client.request(method, path, headers=headers, json={"email": "a@b.c", "password": "x" * 12})
            assert res.status_code == 403, (method, path)
            body = res.json()
            assert body["error"]["code"] == "forbidden"
            assert body["error"]["request_id"] == res.headers["x-request-id"]
            assert ACCESS_KEY not in res.text

    def test_correct_key_reaches_the_app_and_full_flow_works(self, keyed_client: TestClient) -> None:
        keyed_client.headers[HEADER] = ACCESS_KEY
        assert keyed_client.get("/api/v1/health/ready").status_code == 200
        sign_up(keyed_client)
        assert keyed_client.get("/api/v1/auth/me").status_code == 200

    def test_key_is_never_logged(self, keyed_client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level("DEBUG")
        keyed_client.get("/api/v1/auth/me", headers={HEADER: ACCESS_KEY})
        keyed_client.get("/api/v1/auth/me", headers={HEADER: "wrong-key-value"})
        assert ACCESS_KEY not in caplog.text
        assert "wrong-key-value" not in caplog.text

    def test_disabled_by_default(self, client: TestClient) -> None:
        assert client.get("/api/v1/health/ready").status_code == 200

    def test_production_fails_closed_without_a_key(self) -> None:
        base: dict[str, Any] = {
            "_env_file": None,
            "app_env": "production",
            "gemini_api_key": "k",
            "database_url": "postgresql://u:p@h/db",
            "cors_origins": "https://app.example.com",
        }
        with pytest.raises(ValidationError, match="BACKEND_ACCESS_KEY must be set in production"):
            Settings(**base)
        with pytest.raises(ValidationError, match="BACKEND_ACCESS_KEY must be set in production"):
            Settings(**base, backend_access_key="   ")  # blank counts as missing

    def test_production_requires_a_long_key(self) -> None:
        base: dict[str, Any] = {
            "_env_file": None,
            "app_env": "production",
            "gemini_api_key": "k",
            "database_url": "postgresql://u:p@h/db",
            "cors_origins": "https://app.example.com",
        }
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(**base, backend_access_key="short")
        assert Settings(**base, backend_access_key=ACCESS_KEY).backend_access_key is not None

    def test_blank_key_outside_production_disables_the_check(self, tmp_path: Path) -> None:
        assert make_settings(tmp_path, backend_access_key="  ").backend_access_key is None


class TestCacheHeaders:
    def test_api_responses_default_to_no_store(self, client: TestClient) -> None:
        assert client.get("/api/v1/health").headers["cache-control"] == "no-store"
        assert client.get("/api/does-not-exist").headers["cache-control"] == "no-store"
        assert client.get("/api/v1/auth/me").headers["cache-control"] == "no-store"

    def test_header_is_not_duplicated(self, client: TestClient) -> None:
        res = client.get("/api/v1/health")
        assert len([v for k, v in res.headers.multi_items() if k == "cache-control"]) == 1


class TestOperatorCli:
    def test_check_config_prints_summary_without_secrets(self, tmp_path: Path) -> None:
        settings = make_settings(
            tmp_path,
            database_url="postgresql://user:hunter2-secret@db.internal:5432/app",
            gemini_api_key="gemini-secret-value",
            backend_access_key=ACCESS_KEY,
        )
        io = RecordingIo()
        assert cli.main(["check-config"], settings=settings, io=io) == 0
        assert "Configuration OK" in io.text
        assert "key set" in io.text
        assert "backend access key: required" in io.text
        for secret in ("hunter2-secret", "gemini-secret-value", ACCESS_KEY):
            assert secret not in io.text

    def test_invalid_configuration_is_reported_readably_without_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./secret-path-value.db")
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("MAX_UPLOAD_BYTES", "-5")
        monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
        io = RecordingIo()
        assert cli.main(["check-config"], io=io) == 1
        assert io.text.startswith("Configuration error:")
        assert "MAX_UPLOAD_BYTES" in io.text
        assert "secret-path-value" not in io.text
        assert "Traceback" not in io.text

    def test_migrate_reports_progress_and_is_idempotent(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path)
        first, second = RecordingIo(), RecordingIo()
        assert cli.main(["migrate"], settings=settings, io=first) == 0
        assert f"-> {head_revision()}" in first.text
        assert cli.main(["migrate"], settings=settings, io=second) == 0
        assert "Already up to date" in second.text
        assert current_revision(settings.database_url) == head_revision()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="needs TEST_DATABASE_URL (PostgreSQL advisory lock)")
def test_concurrent_migrations_are_serialised_on_postgres(tmp_path: Path) -> None:
    url = make_settings(tmp_path).database_url  # a freshly emptied PostgreSQL schema
    errors: list[BaseException] = []

    def migrate() -> None:
        try:
            run_migrations_exclusively(url)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=migrate) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not errors, errors
    assert current_revision(url) == head_revision()


def test_json_logs_drop_uvicorns_coloured_duplicate_message() -> None:
    import json
    import logging

    from app.core.logging import JsonFormatter

    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "Started server process [%d]", (7,), None)
    record.color_message = "Started server process [\x1b[36m%d\x1b[0m]"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["msg"] == "Started server process [7]"
    assert "color_message" not in payload


def test_app_starts_without_httpx_installed_as_in_the_production_image() -> None:
    """httpx is a dev/test dependency only; the Gemini adapter must import without it."""

    import subprocess
    import sys

    code = (
        "import sys; sys.modules['httpx'] = None\n"  # makes `import httpx` raise ImportError
        "from app.ai.gemini import GeminiProvider, _TIMEOUT_ERRORS\n"
        "from app.application import create_app\n"
        "assert [c.__module__.split('.')[0] for c in _TIMEOUT_ERRORS] == ['httpx2'], _TIMEOUT_ERRORS\n"
        "GeminiProvider(api_key='not-a-real-key', model='m', timeout_seconds=5, max_retries=0,"
        " total_timeout_seconds=5, embedding_model='e', embedding_dimensions=768)\n"
        "print('ok')\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, cwd=BACKEND_DIR, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
