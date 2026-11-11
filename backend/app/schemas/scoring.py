"""Resume quality report (job-independent). Every number is computed by application code."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ATS_DISCLAIMER = (
    "The ATS compatibility score estimates how reliably automated applicant tracking systems can read this "
    "document. It does not predict or guarantee that an application will pass any employer's screening."
)

DimensionKey = Literal[
    "contact", "structure", "summary", "experience", "achievements", "skills", "education", "formatting", "readability"
]


class Deduction(BaseModel):
    code: str
    points: int = Field(ge=0, le=100, description="Points removed from this dimension's 0-100 score.")
    message: str
    recommendation: str
    evidence: str | None = None


class DimensionScore(BaseModel):
    key: DimensionKey
    label: str
    weight: int = Field(description="Share of the overall score, in percent.")
    score: int = Field(ge=0, le=100)
    contribution: float = Field(description="weight x score / 100: points this dimension adds to the overall score.")
    deductions: list[Deduction] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)


class AtsCheck(BaseModel):
    code: str
    passed: bool
    points: int = Field(description="Points deducted from the ATS score when the check fails.")
    message: str
    recommendation: str | None = None


class Recommendation(BaseModel):
    dimension: DimensionKey | Literal["ats"]
    message: str
    recommendation: str
    impact: float = Field(description="Approximate overall-score points recoverable by fixing this.")


class QualityMetrics(BaseModel):
    word_count: int
    bullet_count: int
    quantified_bullet_ratio: float
    action_verb_ratio: float
    reading_ease: float | None
    experience_entries: int
    technical_skill_count: int


class QualityReport(BaseModel):
    scoring_version: str
    overall_score: int = Field(ge=0, le=100)
    label: str
    ats_score: int = Field(ge=0, le=100)
    ats_checks: list[AtsCheck]
    dimensions: list[DimensionScore]
    strengths: list[str]
    weaknesses: list[str]
    missing_information: list[str]
    recommendations: list[Recommendation]
    metrics: QualityMetrics
    score_cap: str | None = Field(default=None, description="Why the overall score was capped, if it was.")
    disclaimer: str = ATS_DISCLAIMER
