"""/api/v1/jobs and /api/v1/matches: submission formats, ownership, CSRF, determinism, fallback, cleanup."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai.base import AIProviderError
from app.db.models import (
    Analysis,
    EmbeddingCacheEntry,
    JobDescription,
    JobMatch,
    JobRequirementRecord,
    MatchingConfigRecord,
    Resume,
)
from app.repositories import jobs as jobs_repo
from app.repositories import matches as matches_repo
from app.repositories import resumes as resumes_repo
from app.services.matches import reproduce_report
from tests.conftest import DEFAULT_PASSWORD, FakeLLM, sign_up
from tests.fixtures.documents import (
    SAMPLE_JD,
    SAMPLE_RESUME_MD,
    docx_paragraph,
    make_docx,
    make_pdf,
)

JOBS = "/api/v1/jobs"
MATCHES = "/api/v1/matches"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def upload_resume(client: TestClient) -> str:
    res = client.post("/api/v1/resumes", files={"file": ("cv.md", SAMPLE_RESUME_MD.encode(), "text/markdown")})
    assert res.status_code == 201, res.text
    resume_id: str = res.json()["id"]
    return resume_id


def submit_job(client: TestClient, text: str = SAMPLE_JD) -> dict[str, Any]:
    res = client.post(JOBS, data={"text": text})
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def create_match(client: TestClient, resume_id: str, job_id: str) -> dict[str, Any]:
    res = client.post(MATCHES, json={"resume_id": resume_id, "job_id": job_id})
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def count(app: FastAPI, model: Any, **filters: Any) -> int:
    with app.state.db.session() as db:
        statement = select(func.count()).select_from(model)
        for column, value in filters.items():
            statement = statement.where(getattr(model, column) == value)
        return int(db.scalar(statement) or 0)


class TestJobSubmission:
    @pytest.mark.parametrize(
        ("kind", "files", "fmt"),
        [
            ("markdown", {"file": ("jd.md", SAMPLE_JD.encode(), "text/markdown")}, "markdown"),
            ("pdf", {"file": ("jd.pdf", make_pdf(SAMPLE_JD), "application/pdf")}, "pdf"),
            (
                "docx",
                {"file": ("jd.docx", make_docx([docx_paragraph(line) for line in SAMPLE_JD.splitlines()]), DOCX_MIME)},
                "docx",
            ),
        ],
    )
    def test_file_formats(self, client: TestClient, kind: str, files: dict[str, Any], fmt: str) -> None:
        res = client.post(JOBS, files=files)
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["source_format"] == fmt
        assert body["source"] == files["file"][0]
        names = {r["name"]: r for r in body["requirements"]}
        assert names["Kubernetes"]["classification"] == "required"
        assert names["Terraform"]["classification"] == "preferred"
        assert names["Terraform"]["classification_source"] == "text"

    def test_pasted_text_returns_structured_job(self, client: TestClient) -> None:
        body = submit_job(client)
        assert body["source"] == "pasted"
        assert body["title"] == "Senior Backend Engineer"
        assert body["company"] == "Globex"
        assert body["requirement_count"] == len(body["requirements"]) == 10
        for requirement in body["requirements"]:
            assert requirement["evidence"] in SAMPLE_JD or requirement["evidence"].rstrip(".") in SAMPLE_JD
        years = next(r for r in body["requirements"] if r["category"] == "experience")
        assert years["min_years"] == 5

    def test_invented_requirements_are_not_saved(self, client: TestClient, fake_llm: FakeLLM) -> None:
        fake_llm.job_response = {
            "requirements": [
                {"name": "Kubernetes", "category": "technical_skill", "evidence": "Kubernetes"},
                {"name": "Security clearance", "category": "certification", "evidence": "Active security clearance"},
            ]
        }
        body = submit_job(client)
        names = [r["name"] for r in body["requirements"] if r["status"] == "verified"]
        assert names == ["Kubernetes"]
        assert body["extraction"]["removed_items"] == 1

    @pytest.mark.parametrize(
        ("data", "files", "message"),
        [
            ({}, None, "either pasted text or a file"),
            ({"text": SAMPLE_JD}, {"file": ("jd.md", SAMPLE_JD.encode(), "text/markdown")}, "not both"),
            ({"text": "Python dev"}, None, "too short"),
            ({"text": "x" * 31_000}, None, "maximum"),
            ({}, {"file": ("jd.exe", b"MZ", "application/octet-stream")}, "Job description file error"),
        ],
    )
    def test_validation(self, client: TestClient, fake_llm: FakeLLM, data: Any, files: Any, message: str) -> None:
        res = client.post(JOBS, data=data, files=files)
        assert res.status_code == 400
        assert message in res.json()["detail"]
        assert fake_llm.call_count == 0

    def test_ai_failure_saves_nothing(self, app: FastAPI, client: TestClient, fake_llm: FakeLLM) -> None:
        fake_llm.job_error = AIProviderError("The AI provider timed out.")
        assert client.post(JOBS, data={"text": SAMPLE_JD}).status_code == 502
        assert count(app, JobDescription) == 0

    def test_ai_not_configured(self, app: FastAPI, client: TestClient) -> None:
        app.state.ai_provider = None
        assert client.post(JOBS, data={"text": SAMPLE_JD}).status_code == 503

    def test_counts_against_ai_quota(self, app: FastAPI, client: TestClient) -> None:
        app.state.settings = app.state.settings.model_copy(update={"ai_max_requests_per_minute": 1})
        submit_job(client)
        assert client.post(JOBS, data={"text": SAMPLE_JD}).status_code == 429

    def test_re_extraction_replaces_requirements(self, client: TestClient, fake_llm: FakeLLM) -> None:
        job = submit_job(client)
        fake_llm.job_response = {
            "requirements": [{"name": "Docker", "category": "technical_skill", "evidence": "Docker"}]
        }
        res = client.post(f"{JOBS}/{job['id']}/extraction")
        assert res.status_code == 200
        verified = [r["name"] for r in res.json()["requirements"] if r["status"] == "verified"]
        assert verified == ["Docker"]

    def test_history_and_retrieval(self, client: TestClient) -> None:
        first = submit_job(client)
        second = submit_job(client, SAMPLE_JD.replace("Globex", "Initech"))
        listing = client.get(JOBS).json()
        assert [j["id"] for j in listing] == [second["id"], first["id"]]
        assert listing[0]["requirement_count"] == 10
        detail = client.get(f"{JOBS}/{first['id']}").json()
        assert detail["text"].startswith("Senior Backend Engineer")
        assert detail["requirements"] == first["requirements"]


class TestMatching:
    def test_match_report(self, app: FastAPI, client: TestClient) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        body = create_match(client, resume_id, job["id"])
        report = body["report"]
        assert body["match_score"] == report["match_score"] == 85
        assert body["label"] == "Strong Match"
        assert body["matching_version"] == "job-match/1"
        assert report["semantic"]["status"] == "available"
        assert {s["name"] for s in report["skills"]["exact"]} >= {"Python", "FastAPI", "Kubernetes"}
        assert [s["name"] for s in report["skills"]["missing"]] == ["Terraform"]
        assert report["qualifications"]["education_matched"][0]["name"].startswith("Bachelor")
        assert report["keywords"]["missing"] == ["Terraform", "GCP"]
        assert report["methodology"]["weights"]["required_skills"] == 35
        assert count(app, MatchingConfigRecord, version="job-match/1") == 1

    def test_identical_inputs_produce_identical_scores_and_reports_reproduce(
        self, app: FastAPI, client: TestClient
    ) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        first = create_match(client, resume_id, job["id"])
        second = create_match(client, resume_id, job["id"])
        assert first["match_score"] == second["match_score"]
        assert first["report"] == second["report"]

        with app.state.db.session() as db:
            match = db.get(JobMatch, first["id"])
            user_id = match.user_id
            resume = resumes_repo.get_resume(db, user_id=user_id, resume_id=resume_id)
            job_row = jobs_repo.get_job(db, user_id=user_id, job_id=job["id"])
            assert resume is not None
            assert job_row is not None
            recomputed = reproduce_report(db, match, resume, job_row)
        assert recomputed.model_dump(mode="json") == first["report"]

    def test_job_changes_match_but_not_resume_quality(self, client: TestClient) -> None:
        resume_id = upload_resume(client)
        quality_before = client.get(f"/api/v1/resumes/{resume_id}").json()["quality"]
        backend = create_match(client, resume_id, submit_job(client)["id"])
        chef_text = "Pastry Chef. Requirements: laminated dough, croissants and early mornings. Nice to have: French."
        client.app.state.ai_provider.job_response = {  # type: ignore[attr-defined]
            "requirements": [{"name": "Laminated dough", "category": "experience", "evidence": "laminated dough"}]
        }
        chef = create_match(client, resume_id, submit_job(client, chef_text)["id"])
        assert chef["match_score"] < backend["match_score"]
        assert client.get(f"/api/v1/resumes/{resume_id}").json()["quality"] == quality_before

    def test_embedding_failure_falls_back_and_is_reported(self, client: TestClient, fake_llm: FakeLLM) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        fake_llm.embed_error = AIProviderError("The embedding service timed out.")
        body = create_match(client, resume_id, job["id"])
        report = body["report"]
        assert body["semantic_status"] == "unavailable"
        assert report["semantic"]["status"] == "unavailable"
        assert "deterministic keyword matching only" in report["semantic"]["reason"]
        assert report["confidence"]["level"] == "medium"
        assert not any(r["match_type"] == "related_semantic" for r in report["requirements"])
        # Lexicon-based related matches still work, and the score stays deterministic.
        assert body["match_score"] == 85

    def test_semantic_related_match_is_labelled_and_never_exact(self, client: TestClient, fake_llm: FakeLLM) -> None:
        resume_id = upload_resume(client)
        fake_llm.job_response = {
            "requirements": [
                {"name": "Docker Swarm", "category": "technical_skill", "evidence": "Docker Swarm experience."}
            ]
        }
        job = submit_job(client, "Platform engineer. Requirements: Docker Swarm experience. Linux administration.")
        fake_llm.make_similar("docker swarm", "kubernetes", 0.88)
        report = create_match(client, resume_id, job["id"])["report"]
        swarm = next(r for r in report["requirements"] if r["name"] == "Docker Swarm")
        assert swarm["status"] == "related"
        assert swarm["match_type"] == "related_semantic"
        assert swarm["related_to"] == "Kubernetes"
        assert swarm["similarity"] == pytest.approx(0.88, abs=1e-3)

    def test_embeddings_are_cached_across_matches(self, client: TestClient, fake_llm: FakeLLM) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        create_match(client, resume_id, job["id"])
        calls = len(fake_llm.embed_calls)
        assert calls >= 1
        create_match(client, resume_id, job["id"])
        assert len(fake_llm.embed_calls) == calls

    def test_cached_match_does_not_consume_ai_quota(self, app: FastAPI, client: TestClient) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        create_match(client, resume_id, job["id"])
        app.state.settings = app.state.settings.model_copy(update={"ai_max_requests_per_minute": 1})
        create_match(client, resume_id, job["id"])  # all embeddings cached: no AI call, no quota use

    def test_list_filter_and_delete(self, app: FastAPI, client: TestClient) -> None:
        resume_id = upload_resume(client)
        job_a = submit_job(client)
        job_b = submit_job(client)
        match_a = create_match(client, resume_id, job_a["id"])
        match_b = create_match(client, resume_id, job_b["id"])
        assert [m["id"] for m in client.get(MATCHES).json()] == [match_b["id"], match_a["id"]]
        assert [m["id"] for m in client.get(MATCHES, params={"job_id": job_a["id"]}).json()] == [match_a["id"]]
        assert client.get(f"{MATCHES}/{match_a['id']}").json()["report"] == match_a["report"]
        assert client.delete(f"{MATCHES}/{match_a['id']}").status_code == 204
        assert client.get(f"{MATCHES}/{match_a['id']}").status_code == 404
        assert client.get(f"{JOBS}/{job_b['id']}").json()["match_count"] == 1

    def test_unknown_resume_or_job(self, client: TestClient) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        assert client.post(MATCHES, json={"resume_id": "nope", "job_id": job["id"]}).status_code == 404
        assert client.post(MATCHES, json={"resume_id": resume_id, "job_id": "nope"}).status_code == 404
        assert client.post(MATCHES, json={"resume_id": resume_id}).status_code == 422


class TestDeletionAndCleanup:
    def test_deleting_a_job_removes_requirements_matches_and_linked_analyses(
        self, app: FastAPI, client: TestClient
    ) -> None:
        analysis = client.post(
            "/api/analyze",
            files={"resume": ("cv.md", SAMPLE_RESUME_MD.encode(), "text/markdown")},
            data={"jd_text": SAMPLE_JD},
        ).json()
        with app.state.db.session() as db:
            job_id = db.get(JobMatch, analysis["job_match_id"]).job_description_id
        assert client.delete(f"{JOBS}/{job_id}").status_code == 204
        assert count(app, JobDescription) == 0
        assert count(app, JobRequirementRecord) == 0
        assert count(app, JobMatch) == 0
        assert count(app, Analysis) == 0
        assert count(app, Resume) == 1  # the resume itself is kept

    def test_deleting_a_resume_removes_its_matches(self, app: FastAPI, client: TestClient) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        create_match(client, resume_id, job["id"])
        assert client.delete(f"/api/v1/resumes/{resume_id}").status_code == 204
        assert count(app, JobMatch) == 0
        assert count(app, JobDescription) == 1

    def test_account_deletion_removes_all_new_records(self, app: FastAPI, client: TestClient) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        create_match(client, resume_id, job["id"])
        user_id = client.get("/api/v1/auth/me").json()["user"]["id"]
        assert count(app, EmbeddingCacheEntry, user_id=user_id) > 0
        res = client.request(
            "DELETE", "/api/v1/auth/me", json={"password": DEFAULT_PASSWORD, "confirmation": "delete my account"}
        )
        assert res.status_code == 204
        for model in (JobDescription, JobRequirementRecord, JobMatch, EmbeddingCacheEntry):
            assert count(app, model, user_id=user_id) == 0
        # Shared, non-personal skill-term embeddings may remain.
        with app.state.db.session() as db:
            assert all(row.user_id is None for row in db.scalars(select(EmbeddingCacheEntry)))


class TestAccessControl:
    def test_other_users_cannot_read_match_or_delete(
        self, client: TestClient, new_client: Callable[[], TestClient]
    ) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        match = create_match(client, resume_id, job["id"])

        other = new_client()
        sign_up(other, "other@example.com")
        other_resume = upload_resume(other)
        assert other.get(JOBS).json() == []
        assert other.get(MATCHES).json() == []
        for method, path in (
            ("GET", f"{JOBS}/{job['id']}"),
            ("DELETE", f"{JOBS}/{job['id']}"),
            ("POST", f"{JOBS}/{job['id']}/extraction"),
            ("GET", f"{MATCHES}/{match['id']}"),
            ("DELETE", f"{MATCHES}/{match['id']}"),
        ):
            res = other.request(method, path)
            assert res.status_code == 404, (method, path)
            assert "Globex" not in res.text
        # Cannot match their own resume against someone else's job, or vice versa.
        assert other.post(MATCHES, json={"resume_id": other_resume, "job_id": job["id"]}).status_code == 404
        assert other.post(MATCHES, json={"resume_id": resume_id, "job_id": job["id"]}).status_code == 404
        assert other.get(MATCHES, params={"job_id": job["id"]}).json() == []
        assert client.get(f"{MATCHES}/{match['id']}").status_code == 200

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", JOBS),
            ("GET", f"{JOBS}/x"),
            ("POST", JOBS),
            ("GET", MATCHES),
            ("POST", MATCHES),
            ("DELETE", f"{MATCHES}/x"),
        ],
    )
    def test_anonymous_rejected(self, anon_client: TestClient, method: str, path: str) -> None:
        assert anon_client.request(method, path).status_code == 401

    def test_state_changes_require_csrf(self, client: TestClient, fake_llm: FakeLLM) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        calls = fake_llm.call_count
        token = client.headers.pop("X-CSRF-Token")
        assert client.post(JOBS, data={"text": SAMPLE_JD}).status_code == 403
        assert client.post(MATCHES, json={"resume_id": resume_id, "job_id": job["id"]}).status_code == 403
        assert client.delete(f"{JOBS}/{job['id']}").status_code == 403
        assert fake_llm.call_count == calls
        client.headers["X-CSRF-Token"] = token
        assert (
            client.post(
                MATCHES,
                json={"resume_id": resume_id, "job_id": job["id"]},
                headers={"Origin": "https://evil.example.com"},
            ).status_code
            == 403
        )

    def test_repositories_are_user_scoped(self, app: FastAPI, client: TestClient) -> None:
        resume_id = upload_resume(client)
        job = submit_job(client)
        match = create_match(client, resume_id, job["id"])
        with app.state.db.session() as db:
            assert jobs_repo.get_job(db, user_id="someone-else", job_id=job["id"]) is None
            assert matches_repo.get_match(db, user_id="someone-else", match_id=match["id"]) is None
            assert not jobs_repo.delete_job(db, user_id="someone-else", job_id=job["id"])
