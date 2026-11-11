"""Cross-cutting behaviour: error envelope, request limits, health, logging, concurrency."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.application import create_app
from tests.conftest import FakeLLM, make_settings, sign_up
from tests.fixtures.documents import SAMPLE_JD, SAMPLE_RESUME_MD


def _analyze(client: TestClient, resume: bytes = SAMPLE_RESUME_MD.encode(), jd: str = SAMPLE_JD):
    return client.post("/api/analyze", files={"resume": ("resume.md", resume, "text/markdown")}, data={"jd_text": jd})


class TestErrorEnvelope:
    def test_app_error_has_envelope_and_request_id(self, client: TestClient) -> None:
        res = client.post(
            "/api/analyze", files={"resume": ("x.exe", b"MZ", "application/octet-stream")}, data={"jd_text": "jd"}
        )
        body = res.json()
        assert res.status_code == 400
        assert body["error"]["code"] == "invalid_file"
        assert body["error"]["message"] == body["detail"]
        assert body["error"]["request_id"] == res.headers["x-request-id"]

    def test_not_found_envelope(self, client: TestClient) -> None:
        body = client.get("/api/analyses/12345").json()
        assert body["error"]["code"] == "not_found"

    def test_unknown_route_envelope(self, client: TestClient) -> None:
        res = client.get("/api/does-not-exist")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

    def test_validation_error_omits_input_values(self, client: TestClient) -> None:
        res = client.get("/api/analyses/not-a-number")
        body = res.json()
        assert res.status_code == 422
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["fields"][0]["loc"] == ["path", "analysis_id"]
        assert "not-a-number" not in res.text

    def test_missing_resume_field_is_422(self, client: TestClient) -> None:
        res = client.post("/api/analyze", data={"jd_text": "jd"})
        assert res.status_code == 422

    def test_unhandled_exception_is_generic_500(self, tmp_path: Path, fake_llm: FakeLLM) -> None:
        app = create_app(make_settings(tmp_path), ai_provider=fake_llm)
        boom = APIRouter()

        @boom.get("/api/boom")
        def _boom() -> None:
            raise RuntimeError("internal secret detail")

        app.include_router(boom)
        with TestClient(app, raise_server_exceptions=False) as test_client:
            res = test_client.get("/api/boom")
        assert res.status_code == 500
        assert res.json()["error"]["code"] == "internal_error"
        assert "internal secret detail" not in res.text

    def test_valid_incoming_request_id_is_echoed(self, client: TestClient) -> None:
        res = client.get("/api/health", headers={"X-Request-ID": "abcdef123456"})
        assert res.headers["x-request-id"] == "abcdef123456"

    def test_malicious_incoming_request_id_is_replaced(self, client: TestClient) -> None:
        res = client.get("/api/health", headers={"X-Request-ID": "bad id\r\ninjected"})
        assert res.headers["x-request-id"] != "bad id\r\ninjected"
        assert len(res.headers["x-request-id"]) == 32


class TestRequestSizeLimit:
    @pytest.fixture
    def small_client(self, tmp_path: Path, fake_llm: FakeLLM) -> Iterator[TestClient]:
        app = create_app(make_settings(tmp_path, max_request_bytes=2048), ai_provider=fake_llm)
        with TestClient(app) as test_client:
            sign_up(test_client)
            yield test_client

    def test_declared_oversized_body_is_rejected_with_413(self, small_client: TestClient) -> None:
        res = _analyze(small_client, resume=b"a" * 4096)
        assert res.status_code == 413
        assert res.json()["error"]["code"] == "payload_too_large"

    def test_chunked_oversized_body_is_rejected_with_413(self, small_client: TestClient) -> None:
        def body() -> Iterator[bytes]:
            for _ in range(10):
                yield b"x" * 1024

        res = small_client.post(
            "/api/analyze",
            content=body(),
            headers={"Content-Type": "multipart/form-data; boundary=zzz"},
        )
        assert res.status_code == 413

    def test_small_body_is_accepted(self, small_client: TestClient) -> None:
        assert _analyze(small_client, resume=b"# Jane\nPython", jd="Python dev").status_code == 200


class TestHealth:
    def test_versioned_liveness(self, client: TestClient) -> None:
        assert client.get("/api/v1/health").json() == {"status": "ok"}

    def test_readiness_reports_missing_ai_provider(self, tmp_path: Path) -> None:
        with TestClient(create_app(make_settings(tmp_path))) as test_client:
            res = test_client.get("/api/v1/health/ready")
        assert res.status_code == 503
        assert res.json()["checks"] == {"database": "ok", "ai_provider": "not_configured"}

    def test_readiness_ok(self, client: TestClient) -> None:
        res = client.get("/api/v1/health/ready")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


class TestAIConfiguration:
    def test_analyze_without_ai_key_returns_503(self, tmp_path: Path) -> None:
        with TestClient(create_app(make_settings(tmp_path))) as test_client:
            sign_up(test_client)
            res = _analyze(test_client)
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "ai_not_configured"

    def test_invalid_upload_reported_before_missing_ai_key(self, tmp_path: Path) -> None:
        with TestClient(create_app(make_settings(tmp_path))) as test_client:
            sign_up(test_client)
            res = test_client.post(
                "/api/analyze", files={"resume": ("r.exe", b"MZ", "application/octet-stream")}, data={"jd_text": "x"}
            )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_file"

    def test_history_still_works_without_ai_key(self, tmp_path: Path) -> None:
        with TestClient(create_app(make_settings(tmp_path))) as test_client:
            sign_up(test_client)
            assert test_client.get("/api/analyses").status_code == 200

    def test_ai_failure_maps_to_502_with_code(self, client: TestClient, fake_llm: FakeLLM) -> None:
        fake_llm.error = TimeoutError()
        res = _analyze(client)
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "ai_upstream_error"


class TestPrivacyInLogs:
    def test_resume_and_jd_content_never_logged(
        self, client: TestClient, fake_llm: FakeLLM, caplog: pytest.LogCaptureFixture
    ) -> None:
        marker_resume = "ZEBRA-RESUME-CONTENT-7731"
        marker_jd = "ZEBRA-JD-CONTENT-4402"
        caplog.set_level(logging.DEBUG)

        _analyze(client, resume=f"# {marker_resume}".encode(), jd=marker_jd)
        # Job matching endpoints (Milestone 4): submission, matching with embeddings, and failures.
        resume_id = client.post(
            "/api/v1/resumes", files={"file": ("cv.md", f"# {marker_resume}".encode(), "text/markdown")}
        ).json()["id"]
        job_text = f"Requirements: Python. {marker_jd} " * 3
        job_id = client.post("/api/v1/jobs", data={"text": job_text}).json()["id"]
        client.post("/api/v1/matches", json={"resume_id": resume_id, "job_id": job_id})
        fake_llm.embed_error = RuntimeError(marker_jd)
        client.post("/api/v1/matches", json={"resume_id": resume_id, "job_id": job_id})

        fake_llm.job_response = "not json"
        _analyze(client, resume=f"# {marker_resume}".encode(), jd=marker_jd)
        fake_llm.error = RuntimeError(marker_resume)
        _analyze(client, resume=f"# {marker_resume}".encode(), jd=marker_jd)

        for record in caplog.records:
            rendered = record.getMessage() + " " + str(vars(record))
            assert marker_resume not in rendered
            assert marker_jd not in rendered

    def test_sensitive_extras_are_redacted_by_formatter(self) -> None:
        from app.core.logging import JsonFormatter, RequestIdFilter

        record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
        record.resume_text = "PRIVATE"
        record.password = "hunter2"
        record.status = 200
        RequestIdFilter().filter(record)
        output = JsonFormatter().format(record)
        assert "PRIVATE" not in output
        assert "hunter2" not in output
        assert '"status": 200' in output


class TestConcurrency:
    def test_server_stays_responsive_during_slow_ai_call(self, client: TestClient, fake_llm: FakeLLM) -> None:
        """Regression for the original blocking `async def` handler."""

        release = threading.Event()
        entered = threading.Event()

        def block() -> None:
            entered.set()
            release.wait(timeout=10)

        fake_llm.before_return = block
        result: dict[str, int] = {}

        worker = threading.Thread(target=lambda: result.setdefault("status", _analyze(client).status_code))
        worker.start()
        try:
            assert entered.wait(timeout=5), "analysis never reached the AI call"
            started = time.perf_counter()
            health = client.get("/api/health")
            elapsed = time.perf_counter() - started
            assert health.status_code == 200
            assert elapsed < 2, f"health check blocked for {elapsed:.2f}s"
        finally:
            release.set()
            worker.join(timeout=10)
        assert result["status"] == 200


class TestCors:
    def test_allowed_origin(self, client: TestClient) -> None:
        res = client.options(
            "/api/analyses",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_disallowed_origin(self, client: TestClient) -> None:
        res = client.options(
            "/api/analyses",
            headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in res.headers
