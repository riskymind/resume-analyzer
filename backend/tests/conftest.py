"""Shared pytest fixtures.

The fake AI provider replaces only the network call: the app's prompt
building, response parsing and validation still run under test, and no real
AI credits are consumed. Each test gets its own SQLite database, created by
running the real Alembic migrations.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.ai.base import AIProviderError  # noqa: E402
from app.application import create_app  # noqa: E402
from app.core.config import Settings  # noqa: E402
from tests.fixtures.documents import SAMPLE_EXTRACTION, SAMPLE_JOB_EXTRACTION, SAMPLE_REWRITE  # noqa: E402

FAKE_EMBEDDING_DIMENSIONS = 64


def _hash_vector(text: str) -> list[float]:
    """Deterministic pseudo-random unit vector; unrelated texts have near-zero cosine similarity."""

    rng = random.Random(hashlib.sha256(text.encode()).digest())  # noqa: S311 - test data
    vector = [rng.gauss(0, 1) for _ in range(FAKE_EMBEDDING_DIMENSIONS)]
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


class FakeLLM:
    """Controllable stand-in implementing the ``AIProvider`` and ``EmbeddingProvider`` protocols."""

    name = "fake"
    embedding_model = "fake-embedding-1"
    embedding_dimensions = FAKE_EMBEDDING_DIMENSIONS

    def __init__(self) -> None:
        # Returned for any other task (no remaining production prompt uses it).
        self.response: dict[str, Any] | str = {}
        # Returned for job-extraction calls.
        self.job_response: dict[str, Any] | str = copy.deepcopy(SAMPLE_JOB_EXTRACTION)
        self.job_error: Exception | None = None
        # Embeddings: texts embedded per call, optional failure, and fixed vectors by normalised text.
        self.embed_calls: list[list[str]] = []
        self.embed_error: Exception | None = None
        self.vectors: dict[str, list[float]] = {}
        # Returned for resume-extraction calls (routed by the TASK marker in the system prompt).
        self.extraction_response: dict[str, Any] | str = copy.deepcopy(SAMPLE_EXTRACTION)
        self.extraction_error: Exception | None = None
        # Returned for resume-rewrite calls: a dict/str, or a callable taking the prompt and returning a dict.
        self.rewrite_response: Any = copy.deepcopy(SAMPLE_REWRITE)
        self.rewrite_error: Exception | None = None
        self.rewrite_prompts: list[str] = []
        self.error: Exception | None = None
        self.prompts: list[str] = []
        self.systems: list[str] = []
        # Non-content arguments of every generate_json call (task label, schema, output cap).
        self.generate_calls: list[dict[str, Any]] = []
        self.before_return: Any = None  # optional hook, e.g. to block for concurrency tests

    def raw_text(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.before_return is not None:
            self.before_return()
        if self.error is not None:
            if isinstance(self.error, AIProviderError):
                raise self.error
            # Adapters convert SDK/network failures into AIProviderError.
            raise AIProviderError("The AI provider request failed.") from self.error
        if isinstance(self.response, str):
            if not self.response.strip():
                raise AIProviderError("The AI provider returned an empty response.")
            return self.response
        return json.dumps(self.response)

    def make_similar(self, anchor: str, other: str, similarity: float) -> None:
        """Fix the vectors of two (normalised) texts so their cosine similarity equals ``similarity``."""

        base = _hash_vector(anchor)
        noise = _hash_vector("orthogonal:" + other)
        dot = sum(a * b for a, b in zip(base, noise, strict=True))
        ortho = [n - dot * b for n, b in zip(noise, base, strict=True)]
        norm = math.sqrt(sum(x * x for x in ortho))
        ortho = [x / norm for x in ortho]
        self.vectors[anchor] = base
        self.vectors[other] = [
            similarity * b + math.sqrt(1 - similarity**2) * o for b, o in zip(base, ortho, strict=True)
        ]

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        if self.embed_error is not None:
            raise (
                self.embed_error
                if isinstance(self.embed_error, AIProviderError)
                else AIProviderError("The embedding request failed.")
            )
        return [self.vectors.get(text, _hash_vector(text)) for text in texts]

    @property
    def embedded_texts(self) -> list[str]:
        return [text for call in self.embed_calls for text in call]

    def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
        task: str = "generate",
    ) -> str:
        self.systems.append(system)
        self.generate_calls.append({"task": task, "json_schema": json_schema, "max_output_tokens": max_output_tokens})
        if system.startswith("TASK: job-extraction"):
            self.prompts.append(prompt)
            failure = self.job_error or self.error
            if failure is not None:
                raise (
                    failure
                    if isinstance(failure, AIProviderError)
                    else AIProviderError("The AI provider request failed.")
                )
            job = self.job_response
            return job if isinstance(job, str) else json.dumps(job)
        if system.startswith("TASK: resume-rewrite"):
            self.prompts.append(prompt)
            self.rewrite_prompts.append(prompt)
            failure = self.rewrite_error or self.error
            if failure is not None:
                raise (
                    failure
                    if isinstance(failure, AIProviderError)
                    else AIProviderError("The AI provider request failed.")
                )
            rewrite = self.rewrite_response(prompt) if callable(self.rewrite_response) else self.rewrite_response
            return rewrite if isinstance(rewrite, str) else json.dumps(rewrite)
        if system.startswith("TASK: resume-extraction"):
            self.prompts.append(prompt)
            if self.before_return is not None:
                self.before_return()
            failure = self.extraction_error or self.error
            if failure is not None:
                raise (
                    failure
                    if isinstance(failure, AIProviderError)
                    else AIProviderError("The AI provider request failed.")
                )
            response = self.extraction_response
            return response if isinstance(response, str) else json.dumps(response)
        return self.raw_text(prompt)

    @property
    def call_count(self) -> int:
        return len(self.prompts)


# Set TEST_DATABASE_URL=postgresql://... to run the suite against PostgreSQL
# (used in CI). The schema is dropped and recreated for every app instance.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _fresh_postgres_url() -> str:
    import sqlalchemy as sa

    assert TEST_DATABASE_URL is not None
    url = Settings(_env_file=None, database_url=TEST_DATABASE_URL).database_url
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA public CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA public"))
    engine.dispose()
    return url


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    if "database_url" not in overrides:
        overrides["database_url"] = (
            _fresh_postgres_url() if TEST_DATABASE_URL else f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
        )
    values: dict[str, Any] = {
        "app_env": "test",
        "gemini_api_key": None,
        "auto_migrate": True,
        "log_format": "text",
        "cors_origins": ["http://localhost:5173"],
        # Cheap Argon2 parameters keep the suite fast; production uses the defaults.
        "password_hash_time_cost": 1,
        "password_hash_memory_kib": 1024,
        "password_hash_parallelism": 1,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


DEFAULT_PASSWORD = "correct horse battery"


def sign_up(client: TestClient, email: str = "owner@example.com", password: str = DEFAULT_PASSWORD) -> dict[str, Any]:
    """Register (which also signs in) and attach the CSRF header for later requests."""

    res = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return body


@pytest.fixture
def app(settings: Settings, fake_llm: FakeLLM) -> Iterator[FastAPI]:
    application = create_app(settings, ai_provider=fake_llm)
    with TestClient(application):  # runs lifespan (migrations) once
        yield application


@pytest.fixture
def new_client(app: FastAPI) -> Iterator[Callable[[], TestClient]]:
    """Factory for extra clients with their own cookie jars (other users / anonymous)."""

    clients: list[TestClient] = []

    def factory() -> TestClient:
        test_client = TestClient(app)
        clients.append(test_client)
        return test_client

    yield factory
    for test_client in clients:
        test_client.close()


@pytest.fixture
def anon_client(new_client: Callable[[], TestClient]) -> TestClient:
    return new_client()


@pytest.fixture
def client(new_client: Callable[[], TestClient]) -> TestClient:
    """A signed-in client (owner@example.com) with the CSRF header attached."""

    test_client = new_client()
    sign_up(test_client)
    return test_client
