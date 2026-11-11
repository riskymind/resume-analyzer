"""Schemas for the original resume-vs-JD fit analysis API (contract unchanged)."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.scoring import QualityReport


class Recommendations(BaseModel):
    """Structured recommendations returned alongside a fitment score."""

    missing_keywords: list[str]
    phrasing_suggestions: list[str]
    skill_gaps: list[str]
    formatting_notes: list[str]


class AnalysisResult(BaseModel):
    """The outcome of comparing a resume against a job description."""

    score: int
    score_label: str
    recommendations: Recommendations


class AnalysisRecord(BaseModel):
    """A full persisted analysis, reproducible without re-calling the LLM."""

    id: int
    created_at: str
    resume_filename: str
    jd_source: str
    result: AnalysisResult
    # Added in Milestone 3 (additive; absent/null for analyses created earlier).
    resume_id: str | None = None
    resume_quality: QualityReport | None = None
    # Added in Milestone 4: the deterministic match report that produced ``result.score``.
    job_match_id: str | None = None


class AnalysisListItem(BaseModel):
    """A lightweight row shown in the analysis history list."""

    id: int
    created_at: str
    resume_filename: str
    score: int
    score_label: str
