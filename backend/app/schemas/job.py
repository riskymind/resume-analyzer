"""Structured job description schema.

Every requirement keeps the verbatim job-description text it came from
(``evidence``). Requirements reach this schema only after application code has
confirmed that evidence in the original text (``app.services.job_extraction``);
anything the model proposed that cannot be found there is discarded.

- ``status``: ``verified`` - proposed by the AI and confirmed against the text;
  ``detected`` - found by the deterministic skill lexicon scan (the AI missed it).
- ``classification_source``: ``text`` - required/preferred decided by wording in
  the job description itself ("nice to have", "required", section headings);
  ``ai`` - the text was ambiguous, so the model's classification was kept;
  ``default`` - neither gave a usable answer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.resume import AIValue, TextField

RequirementCategory = Literal[
    "technical_skill", "soft_skill", "experience", "education", "certification", "responsibility"
]
Classification = Literal["required", "preferred"]
Importance = Literal["high", "medium", "low"]
RequirementStatus = Literal["verified", "detected"]
ClassificationSource = Literal["text", "ai", "default"]

REQUIREMENT_CATEGORIES: tuple[RequirementCategory, ...] = (
    "technical_skill",
    "soft_skill",
    "experience",
    "education",
    "certification",
    "responsibility",
)


class JobRequirement(BaseModel):
    id: str = Field(description="Stable identifier within this job description, e.g. 'r3'.")
    name: str
    category: RequirementCategory
    classification: Classification
    classification_source: ClassificationSource
    importance: Importance
    evidence: str = Field(description="Verbatim text from the job description supporting this requirement.")
    status: RequirementStatus
    min_years: float | None = Field(default=None, description="Minimum years, only when stated in the evidence.")
    alternative_group: str | None = Field(
        default=None, description="Requirements sharing a group are alternatives ('FastAPI or Django'): one suffices."
    )


class JobKeyword(BaseModel):
    term: str
    evidence: str | None = None


class JobInfo(BaseModel):
    title: TextField = Field(default_factory=TextField)
    company: TextField = Field(default_factory=TextField)
    location: TextField = Field(default_factory=TextField)
    work_arrangement: TextField = Field(default_factory=TextField)
    employment_type: TextField = Field(default_factory=TextField)
    seniority: TextField = Field(default_factory=TextField)


class JobExtractionInfo(BaseModel):
    method: Literal["ai+verification"] = "ai+verification"
    provider: str
    prompt_version: str
    removed_items: int = 0
    reclassified_items: int = 0
    detected_items: int = 0
    warnings: list[str] = Field(default_factory=list)


class StructuredJob(BaseModel):
    info: JobInfo = Field(default_factory=JobInfo)
    requirements: list[JobRequirement] = Field(default_factory=list)
    keywords: list[JobKeyword] = Field(default_factory=list)
    extraction: JobExtractionInfo


# --------------------------------------------------------------------------- model output (untrusted)

_MAX_TEXT = 1000


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AIRequirement(_Lenient):
    name: str = Field(max_length=200)
    category: str = Field(default="", max_length=40)
    classification: str = Field(default="", max_length=40)
    importance: str = Field(default="medium", max_length=20)
    evidence: str | None = Field(default=None, max_length=_MAX_TEXT)
    min_years: float | None = None


class AIKeyword(_Lenient):
    term: str = Field(max_length=80)
    evidence: str | None = Field(default=None, max_length=_MAX_TEXT)


class AIJobExtraction(_Lenient):
    """Exactly what the model is asked to return. Nothing here is trusted."""

    title: AIValue | None = None
    company: AIValue | None = None
    location: AIValue | None = None
    work_arrangement: AIValue | None = None
    employment_type: AIValue | None = None
    seniority: AIValue | None = None
    requirements: list[AIRequirement] = Field(default_factory=list, max_length=120)
    keywords: list[AIKeyword] = Field(default_factory=list, max_length=80)
