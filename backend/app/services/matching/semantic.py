"""Semantic similarity signals from embeddings (approved decision D7), with a persistent cache.

Only short, relevant texts are embedded: requirement skill names, resume skill
names, requirement sentences for experience/responsibility requirements, and
individual resume bullets. Whole resumes are never embedded.

Cache keys are SHA-256 digests of ``model | dimensions | scope | normalised
text``, so a model or dimension change never reuses stale vectors. Short skill
terms are cached globally (they are not personal data); longer texts are
cached per user and deleted with the account.

Failure never breaks matching: any provider error yields
``status="unavailable"`` with a reason, and the engine falls back to
deterministic matching only. Similarities are rounded to 4 decimals so the
downstream score is stable across platforms.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import unicodedata
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.ai.base import AIProviderError, EmbeddingProvider
from app.db.types import utcnow
from app.repositories import embeddings as cache_repo
from app.schemas.job import StructuredJob
from app.schemas.matching import SemanticPair, SemanticSignals
from app.schemas.resume import StructuredResume

logger = logging.getLogger(__name__)

SHARED_TERM_MAX_CHARS = 60
MAX_TEXT_CHARS = 400


def normalize_for_embedding(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text[:MAX_TEXT_CHARS]


def cache_key(*, model: str, dimensions: int, text: str, user_id: str | None) -> str:
    scope = user_id or "*"
    return hashlib.sha256(f"{model}\x1f{dimensions}\x1f{scope}\x1f{text}".encode()).hexdigest()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return round(dot / norm, 4) if norm else 0.0


class _Batch:
    """Collects texts, resolves vectors from the cache, and embeds only the misses."""

    def __init__(self, provider: EmbeddingProvider, user_id: str) -> None:
        self.provider = provider
        self.user_id = user_id
        self.keys: dict[str, tuple[str, str | None]] = {}  # normalised text -> (key, owner)

    def add(self, text: str) -> str:
        normalised = normalize_for_embedding(text)
        if normalised and normalised not in self.keys:
            owner = None if len(normalised) <= SHARED_TERM_MAX_CHARS else self.user_id
            key = cache_key(
                model=self.provider.embedding_model,
                dimensions=self.provider.embedding_dimensions,
                text=normalised,
                user_id=owner,
            )
            self.keys[normalised] = (key, owner)
        return normalised

    def resolve(self, db: Session, before_remote_call: Callable[[], None] | None) -> tuple[dict[str, list[float]], int]:
        cached = cache_repo.get_many(db, [key for key, _ in self.keys.values()])
        vectors = {text: cached[key] for text, (key, _) in self.keys.items() if key in cached}
        missing = [text for text in self.keys if text not in vectors]
        if missing:
            if before_remote_call is not None:
                before_remote_call()
            fresh = self.provider.embed(missing)
            dims = self.provider.embedding_dimensions
            if len(fresh) != len(missing) or any(len(v) != dims or not all(math.isfinite(x) for x in v) for v in fresh):
                raise AIProviderError("The embedding service returned vectors of an unexpected shape.")
            now = utcnow()
            rows: list[dict[str, Any]] = []
            for text, vector in zip(missing, fresh, strict=True):
                key, owner = self.keys[text]
                vectors[text] = vector
                rows.append(
                    {
                        "key": key,
                        "user_id": owner,
                        "model": self.provider.embedding_model,
                        "dimensions": dims,
                        "vector": vector,
                        "created_at": now,
                    }
                )
            cache_repo.put_many(db, rows)
        return vectors, len(missing)


def _best(query: str, candidates: list[tuple[str, str]], vectors: dict[str, list[float]]) -> SemanticPair | None:
    """Highest-similarity candidate; ties keep the earliest candidate (stable)."""

    best: SemanticPair | None = None
    query_vector = vectors.get(query)
    if query_vector is None:
        return None
    for normalised, original in candidates:
        vector = vectors.get(normalised)
        if vector is None:
            continue
        similarity = cosine(query_vector, vector)
        if best is None or similarity > best.similarity:
            best = SemanticPair(resume_text=original, similarity=similarity)
    return best


def compute_signals(
    db: Session,
    provider: EmbeddingProvider | None,
    *,
    enabled: bool,
    user_id: str,
    resume: StructuredResume,
    job: StructuredJob,
    max_texts: int,
    before_remote_call: Callable[[], None] | None = None,
) -> SemanticSignals:
    if not enabled:
        return SemanticSignals(status="disabled", reason="Semantic matching is disabled on this server.")
    if provider is None:
        return SemanticSignals(status="disabled", reason="No embedding provider is configured on this server.")

    model = f"{provider.name}:{provider.embedding_model}"
    skill_reqs = [r for r in job.requirements if r.category in ("technical_skill", "soft_skill")]
    text_reqs = [
        r
        for r in job.requirements
        if r.category == "responsibility" or (r.category == "experience" and r.min_years is None)
    ]
    if not skill_reqs and not text_reqs:
        return SemanticSignals(status="available", model=model)

    batch = _Batch(provider, user_id)
    tech_names = [s.name for s in resume.technical_skills] + [t for p in resume.projects for t in p.technologies]
    soft_names = [s.name for s in resume.soft_skills]
    units = [resume.summary.value] if resume.summary.present and resume.summary.value else []
    units += [b.text for entry in resume.experience for b in entry.bullets]
    units += [p.description.value for p in resume.projects if p.description.present and p.description.value]

    budget = max_texts - len(skill_reqs) - len(text_reqs) - len(tech_names) - len(soft_names)
    units = units[: max(budget, 0)]

    tech = [(batch.add(name), name) for name in dict.fromkeys(tech_names)]
    soft = [(batch.add(name), name) for name in dict.fromkeys(soft_names)]
    unit_pairs = [(batch.add(text), text) for text in units]
    skill_queries = {r.id: batch.add(r.name) for r in skill_reqs}
    text_queries = {r.id: batch.add(r.evidence) for r in text_reqs}

    try:
        vectors, embedded = batch.resolve(db, before_remote_call)
    except AIProviderError as exc:
        logger.warning("semantic_matching_unavailable", extra={"provider": provider.name})
        return SemanticSignals(
            status="unavailable",
            model=model,
            reason=f"{exc} Results use deterministic keyword matching only.",
        )

    signals = SemanticSignals(status="available", model=model)
    for req in skill_reqs:
        pool = soft if req.category == "soft_skill" else tech
        pair = _best(skill_queries[req.id], pool, vectors)
        if pair is not None:
            signals.skill_pairs[req.id] = pair
    for req in text_reqs:
        pair = _best(text_queries[req.id], unit_pairs, vectors)
        if pair is not None:
            signals.text_pairs[req.id] = pair
    logger.info("semantic_signals", extra={"texts": len(batch.keys), "embedded": embedded})
    return signals
