"""Pydantic request/response schemas shared across backend routes."""

from pydantic import BaseModel


class Recommendations(BaseModel):
    """Structured recommendations returned alongside a fitment score."""

    missing_keywords: list[str]
    phrasing_suggestions: list[str]
    skill_gaps: list[str]
    formatting_notes: list[str]


class AnalysisResult(BaseModel):
    """The LLM-derived outcome of comparing a resume against a job description."""

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


class AnalysisListItem(BaseModel):
    """A lightweight row shown in the analysis history list."""

    id: int
    created_at: str
    resume_filename: str
    score: int
    score_label: str
