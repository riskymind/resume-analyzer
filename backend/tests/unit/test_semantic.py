"""Semantic signals: embedding cache, stable keys, user scoping and graceful fallback."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.base import AIProviderError
from app.core.errors import RateLimitedError
from app.db.models import EmbeddingCacheEntry, User
from app.db.session import Database
from app.services.matching.semantic import SHARED_TERM_MAX_CHARS, cache_key, compute_signals, normalize_for_embedding
from tests.conftest import FakeLLM, make_settings
from tests.unit.test_matching_engine import make_job, make_resume, r

LONG_REQUIREMENT = "Design, build and operate highly available payment APIs used by millions of customers."


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Session]:
    database = Database(make_settings(tmp_path).database_url)
    database.migrate()
    with database.session() as session:
        for user_id in ("u1", "u2"):
            session.add(User(id=user_id, email=f"{user_id}@example.com", password_hash="x"))
        session.commit()
        yield session
    database.dispose()


def signals(db: Session, llm: FakeLLM | None, *, user_id: str = "u1", enabled: bool = True, **kwargs):
    resume, _ = make_resume()
    job = make_job(r("r1", "FastAPI"), r("r2", "Leadership", "soft_skill"), r("r3", LONG_REQUIREMENT, "responsibility"))
    return compute_signals(db, llm, enabled=enabled, user_id=user_id, resume=resume, job=job, max_texts=150, **kwargs)


def test_cache_key_is_stable_and_scoped() -> None:
    base = {"model": "m1", "dimensions": 768, "text": "kubernetes", "user_id": None}
    assert cache_key(**base) == cache_key(**base)  # type: ignore[arg-type]
    assert cache_key(**base) != cache_key(**{**base, "model": "m2"})  # type: ignore[arg-type]
    assert cache_key(**base) != cache_key(**{**base, "dimensions": 256})  # type: ignore[arg-type]
    assert cache_key(**base) != cache_key(**{**base, "user_id": "u1"})  # type: ignore[arg-type]
    assert normalize_for_embedding("  Kubernetes\n ") == normalize_for_embedding("kubernetes")


def test_best_pairs_are_computed(db: Session, fake_llm: FakeLLM) -> None:
    fake_llm.make_similar("fastapi", "django", 0.9)
    result = signals(db, fake_llm)
    assert result.status == "available"
    assert result.skill_pairs["r1"].resume_text == "Django"
    assert result.skill_pairs["r1"].similarity == pytest.approx(0.9, abs=1e-4)
    assert "r3" in result.text_pairs


def test_second_run_uses_cache_without_calling_the_provider(db: Session, fake_llm: FakeLLM) -> None:
    first = signals(db, fake_llm)
    db.commit()
    calls = len(fake_llm.embed_calls)
    second = signals(db, fake_llm)
    assert len(fake_llm.embed_calls) == calls  # no new embedding calls
    assert first == second


def test_whole_resume_is_never_embedded(db: Session, fake_llm: FakeLLM) -> None:
    signals(db, fake_llm)
    _, full_text = make_resume()
    assert normalize_for_embedding(full_text) not in fake_llm.embedded_texts
    assert all(len(text) <= 400 for text in fake_llm.embedded_texts)


def test_long_texts_are_cached_per_user_short_terms_shared(db: Session, fake_llm: FakeLLM) -> None:
    signals(db, fake_llm, user_id="u1")
    db.commit()
    rows = db.execute(select(EmbeddingCacheEntry.user_id, func.count()).group_by(EmbeddingCacheEntry.user_id)).all()
    owners = dict(rows)
    assert owners.get(None, 0) > 0  # skill names
    assert owners.get("u1", 0) > 0  # bullets / requirement sentences

    calls = len(fake_llm.embed_calls)
    signals(db, fake_llm, user_id="u2")
    new_texts = [t for call in fake_llm.embed_calls[calls:] for t in call]
    assert new_texts, "another user's personal texts must not be served from u1's cache"
    assert all(len(text) > SHARED_TERM_MAX_CHARS for text in new_texts)


def test_provider_failure_falls_back_with_reason(db: Session, fake_llm: FakeLLM) -> None:
    fake_llm.embed_error = AIProviderError("The embedding service timed out.", retryable=True)
    result = signals(db, fake_llm)
    assert result.status == "unavailable"
    assert result.skill_pairs == {}
    assert "timed out" in (result.reason or "")
    assert "deterministic keyword matching only" in (result.reason or "")


def test_bad_vector_shape_is_treated_as_failure(db: Session, fake_llm: FakeLLM) -> None:
    fake_llm.embedding_dimensions = 32  # provider claims 32 dims but returns 64
    assert signals(db, fake_llm).status == "unavailable"


def test_disabled_and_missing_provider(db: Session, fake_llm: FakeLLM) -> None:
    assert signals(db, fake_llm, enabled=False).status == "disabled"
    assert signals(db, None).status == "disabled"
    assert fake_llm.embed_calls == []


def test_quota_hook_runs_only_when_embeddings_are_fetched(db: Session, fake_llm: FakeLLM) -> None:
    hits: list[int] = []
    signals(db, fake_llm, before_remote_call=lambda: hits.append(1))
    db.commit()
    signals(db, fake_llm, before_remote_call=lambda: hits.append(1))
    assert hits == [1]


def test_quota_exceeded_propagates(db: Session, fake_llm: FakeLLM) -> None:
    def deny() -> None:
        raise RateLimitedError("slow down", retry_after_seconds=10)

    with pytest.raises(RateLimitedError):
        signals(db, fake_llm, before_remote_call=deny)
    assert fake_llm.embed_calls == []
