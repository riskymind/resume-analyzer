"""/api/v1/resumes and the resume pipeline inside the original /api/analyze."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select

from app.ai.base import AIProviderError
from app.db.models import Analysis, Resume, ResumeAnalysis
from tests.conftest import FakeLLM, sign_up
from tests.fixtures.documents import SAMPLE_DOCX_BODY, SAMPLE_JD, SAMPLE_RESUME_MD, make_docx, make_pdf

RESUMES = "/api/v1/resumes"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def upload(
    client: TestClient, filename: str = "cv.md", data: bytes | None = None, mime: str = "text/markdown"
) -> Response:
    content = SAMPLE_RESUME_MD.encode() if data is None else data
    return client.post(RESUMES, files={"file": (filename, content, mime)})


def counts(app: FastAPI) -> dict[str, int]:
    with app.state.db.session() as db:
        return {
            model.__tablename__: int(db.scalar(select(func.count()).select_from(model)) or 0)
            for model in (Resume, ResumeAnalysis, Analysis)
        }


class TestUpload:
    @pytest.mark.parametrize(
        ("filename", "data", "mime", "fmt"),
        [
            ("cv.md", SAMPLE_RESUME_MD.encode(), "text/markdown", "markdown"),
            ("cv.pdf", make_pdf(SAMPLE_RESUME_MD), "application/pdf", "pdf"),
            ("cv.docx", make_docx(SAMPLE_DOCX_BODY), DOCX_MIME, "docx"),
        ],
    )
    def test_upload_each_format(self, client: TestClient, filename: str, data: bytes, mime: str, fmt: str) -> None:
        res = upload(client, filename, data, mime)
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["file_format"] == fmt
        assert body["filename"] == filename
        structured = body["structured"]
        assert structured["contact"]["email"]["value"] == "jane.doe@example.com"
        assert any(e["employer"]["value"] == "Acme Corp" for e in structured["experience"])
        quality = body["quality"]
        assert 0 <= quality["overall_score"] <= 100
        assert body["overall_score"] == quality["overall_score"]
        assert {d["key"] for d in quality["dimensions"]} >= {"contact", "experience", "achievements"}
        assert "experience" in [s["kind"] for s in body["sections"]]

    def test_unverifiable_model_output_is_dropped_not_saved(self, client: TestClient, fake_llm: FakeLLM) -> None:
        fake_llm.extraction_response = {
            "experience": [{"title": {"value": "CTO"}, "employer": {"value": "Google"}}],
            "technical_skills": [{"name": "Python"}, {"name": "Quantum Computing"}],
        }
        body = upload(client).json()
        assert body["structured"]["experience"] == []
        assert [s["name"] for s in body["structured"]["technical_skills"]] == ["Python"]
        assert body["structured"]["extraction"]["removed_items"] == 4

    def test_extracted_text_returned_but_original_file_not_stored(self, app: FastAPI, client: TestClient) -> None:
        body = upload(client).json()
        assert body["text"].startswith("# Jane Doe")
        with app.state.db.session() as db:
            stored = db.get(Resume, body["id"])
        assert stored is not None
        assert len(stored.content_sha256) == 64
        assert not hasattr(stored, "file_bytes")


class TestFailures:
    def test_invalid_file_rejected_before_any_ai_call(self, client: TestClient, fake_llm: FakeLLM) -> None:
        res = upload(client, "cv.exe", b"MZ\x90\x00", "application/octet-stream")
        assert res.status_code == 400
        assert fake_llm.call_count == 0

    def test_scanned_pdf_rejected_with_guidance(self, client: TestClient, fake_llm: FakeLLM) -> None:
        res = upload(client, "scan.pdf", make_pdf("Page 1"), "application/pdf")
        assert res.status_code == 400
        assert "text-based PDF or DOCX" in res.json()["detail"]
        assert fake_llm.call_count == 0

    def test_oversized_text_rejected(self, app: FastAPI, client: TestClient) -> None:
        app.state.settings = app.state.settings.model_copy(update={"max_resume_chars": 2000})
        res = upload(client, data=("# Jane\n" + "- Built a reliable thing for users.\n" * 100).encode())
        assert res.status_code == 400
        assert "maximum is 2,000" in res.json()["detail"]

    @pytest.mark.parametrize(
        "failure",
        ["provider_error", "invalid_json", "schema_violation"],
    )
    def test_ai_failure_returns_502_and_saves_nothing(
        self, app: FastAPI, client: TestClient, fake_llm: FakeLLM, failure: str
    ) -> None:
        if failure == "provider_error":
            fake_llm.extraction_error = AIProviderError("The AI provider timed out.")
        elif failure == "invalid_json":
            fake_llm.extraction_response = "{not json"
        else:
            fake_llm.extraction_response = {"experience": "not-a-list"}
        res = upload(client)
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "ai_upstream_error"
        assert counts(app) == {"resumes": 0, "resume_analyses": 0, "analyses": 0}

    def test_fit_analysis_failure_after_extraction_saves_nothing(
        self, app: FastAPI, client: TestClient, fake_llm: FakeLLM
    ) -> None:
        fake_llm.job_response = "not json"  # resume extraction succeeds, job extraction fails
        res = client.post(
            "/api/analyze",
            files={"resume": ("cv.md", SAMPLE_RESUME_MD.encode(), "text/markdown")},
            data={"jd_text": SAMPLE_JD},
        )
        assert res.status_code == 502
        assert counts(app) == {"resumes": 0, "resume_analyses": 0, "analyses": 0}

    def test_ai_not_configured(self, app: FastAPI, client: TestClient) -> None:
        app.state.ai_provider = None
        assert upload(client).status_code == 503

    def test_upload_counts_against_ai_quota(self, app: FastAPI, client: TestClient) -> None:
        app.state.settings = app.state.settings.model_copy(update={"ai_max_requests_per_minute": 1})
        assert upload(client).status_code == 201
        assert upload(client).status_code == 429


class TestAccessControl:
    def test_list_detail_delete(self, app: FastAPI, client: TestClient) -> None:
        first = upload(client).json()
        second = upload(client, "cv.docx", make_docx(SAMPLE_DOCX_BODY), DOCX_MIME).json()
        listing = client.get(RESUMES).json()
        assert [r["id"] for r in listing] == [second["id"], first["id"]]
        assert listing[0]["overall_score"] == second["quality"]["overall_score"]

        detail = client.get(f"{RESUMES}/{first['id']}").json()
        assert detail["quality"] == first["quality"]
        assert detail["structured"] == first["structured"]

        assert client.delete(f"{RESUMES}/{first['id']}").status_code == 204
        assert client.get(f"{RESUMES}/{first['id']}").status_code == 404
        assert counts(app)["resumes"] == 1

    def test_other_users_cannot_see_or_delete(self, client: TestClient, new_client: Callable[[], TestClient]) -> None:
        mine = upload(client).json()
        other = new_client()
        sign_up(other, "other@example.com")
        assert other.get(RESUMES).json() == []
        for method in ("GET", "DELETE"):
            res = other.request(method, f"{RESUMES}/{mine['id']}")
            assert res.status_code == 404
            assert "Jane" not in res.text
        assert client.get(f"{RESUMES}/{mine['id']}").status_code == 200

    @pytest.mark.parametrize(
        ("method", "path"), [("GET", RESUMES), ("GET", f"{RESUMES}/x"), ("DELETE", f"{RESUMES}/x")]
    )
    def test_anonymous_rejected(self, anon_client: TestClient, method: str, path: str) -> None:
        assert anon_client.request(method, path).status_code == 401

    def test_upload_requires_csrf(self, client: TestClient, fake_llm: FakeLLM) -> None:
        del client.headers["X-CSRF-Token"]
        assert upload(client).status_code == 403
        assert fake_llm.call_count == 0

    def test_delete_requires_csrf(self, client: TestClient) -> None:
        resume_id = upload(client).json()["id"]
        del client.headers["X-CSRF-Token"]
        assert client.delete(f"{RESUMES}/{resume_id}").status_code == 403


class TestLegacyIntegration:
    def analyze(self, client: TestClient, jd: str = SAMPLE_JD) -> dict[str, Any]:
        res = client.post(
            "/api/analyze",
            files={"resume": ("cv.md", SAMPLE_RESUME_MD.encode(), "text/markdown")},
            data={"jd_text": jd},
        )
        assert res.status_code == 200, res.text
        body: dict[str, Any] = res.json()
        return body

    def test_analyze_adds_quality_and_resume_link(self, client: TestClient) -> None:
        body = self.analyze(client)
        assert body["result"]["score"] == 85  # deterministic match percentage since Milestone 4
        assert body["job_match_id"]
        assert body["resume_id"]
        assert body["resume_quality"]["overall_score"] >= 0
        detail = client.get(f"/api/analyses/{body['id']}").json()
        assert detail["resume_quality"] == body["resume_quality"]
        assert client.get(f"{RESUMES}/{body['resume_id']}").status_code == 200

    def test_quality_score_does_not_depend_on_the_job(self, client: TestClient) -> None:
        backend = self.analyze(client, SAMPLE_JD)
        unrelated = self.analyze(client, "Pastry chef wanted. Croissants, laminated dough, early mornings.")
        assert backend["resume_quality"] == unrelated["resume_quality"]

    def test_pre_milestone_3_records_have_no_quality(self, app: FastAPI, client: TestClient) -> None:
        body = self.analyze(client)
        with app.state.db.session() as db, db.begin():
            row = db.get(Analysis, body["id"])
            assert row is not None
            row.resume_id = None  # simulate a record created before Milestone 3
        detail = client.get(f"/api/analyses/{body['id']}").json()
        assert detail["resume_quality"] is None
        assert detail["resume_id"] is None
        assert detail["result"] == body["result"]

    def test_deleting_resume_removes_analyses_that_embed_it(self, app: FastAPI, client: TestClient) -> None:
        body = self.analyze(client)
        assert client.delete(f"{RESUMES}/{body['resume_id']}").status_code == 204
        assert client.get(f"/api/analyses/{body['id']}").status_code == 404
        assert counts(app) == {"resumes": 0, "resume_analyses": 0, "analyses": 0}

    def test_docx_resume_and_docx_job_description(self, client: TestClient) -> None:
        res = client.post(
            "/api/analyze",
            files={
                "resume": ("cv.docx", make_docx(SAMPLE_DOCX_BODY), DOCX_MIME),
                "jd_file": (
                    "jd.docx",
                    make_docx(["<w:p><w:r><w:t>Senior Python engineer</w:t></w:r></w:p>"]),
                    DOCX_MIME,
                ),
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["jd_source"] == "jd.docx"
