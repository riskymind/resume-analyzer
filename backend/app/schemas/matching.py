"""Job match report. Every number is computed by application code (``app.services.matching.engine``)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.job import Classification, Importance, RequirementCategory

MATCH_DISCLAIMER = (
    "This match estimates how well the resume evidences the stated job requirements. It cannot see skills the "
    "resume does not mention, and it does not predict any employer's hiring decision."
)

MatchStatus = Literal["matched", "related", "partial", "missing"]
MatchType = Literal[
    "exact",  # named in the resume (or a true alias)
    "evidenced",  # soft skill demonstrated by a verbatim resume sentence
    "related_lexicon",  # a different skill in the same family (e.g. Django for FastAPI)
    "related_semantic",  # embedding similarity above the threshold; never treated as exact
    "years",  # years of experience compared against dated roles / stated years
    "education",  # degree level and field comparison
    "text_overlap",  # experience/responsibility wording overlap with resume bullets
    "semantic_text",  # embedding similarity between requirement and resume bullets
    "none",
]
ComponentKey = Literal[
    "required_skills",
    "experience",
    "responsibilities",
    "education",
    "certifications",
    "preferred_qualifications",
    "keywords",
]
SemanticStatus = Literal["available", "unavailable", "disabled"]


class ResumeEvidence(BaseModel):
    section: str = Field(description="Resume section the evidence comes from, e.g. 'skills', 'experience'.")
    label: str | None = Field(default=None, description="E.g. 'Senior Software Engineer, Acme Corp'.")
    text: str


class RequirementResult(BaseModel):
    requirement_id: str
    name: str
    category: RequirementCategory
    classification: Classification
    importance: Importance
    jd_evidence: str
    status: MatchStatus
    match_type: MatchType
    credit: float = Field(ge=0, le=1, description="Share of this requirement's weight awarded.")
    weight: float = Field(description="Importance weight within its component.")
    component: ComponentKey
    evidence: list[ResumeEvidence] = Field(default_factory=list)
    related_to: str | None = Field(default=None, description="The resume skill a related match is based on.")
    similarity: float | None = None
    candidate_years: float | None = None
    required_years: float | None = None
    alternative_group: str | None = None
    counted: bool = Field(default=True, description="False when an alternative requirement in the group was used.")
    satisfied_by_alternative: str | None = None
    explanation: str


class ComponentScore(BaseModel):
    key: ComponentKey
    label: str
    weight: int = Field(description="Configured share of the score, in percent.")
    effective_weight: float = Field(description="Share after re-normalising over components that apply to this job.")
    score: int | None = Field(ge=0, le=100, description="0-100, or null when the job has no such requirements.")
    contribution: float = Field(description="Points this component adds to the match percentage.")
    requirement_ids: list[str]


class SkillRef(BaseModel):
    requirement_id: str
    name: str
    classification: Classification
    category: RequirementCategory
    resume_term: str | None = None


class SkillsAnalysis(BaseModel):
    exact: list[SkillRef]
    related: list[SkillRef]
    missing: list[SkillRef]
    required_total: int
    preferred_total: int


class SeniorityAlignment(BaseModel):
    job_level: str | None
    resume_level: str | None
    status: Literal["aligned", "below", "above", "unknown"]
    explanation: str


class ExperienceAnalysis(BaseModel):
    candidate_years: float | None = Field(description="Total years across dated roles (overlaps merged).")
    stated_years: float | None = Field(description="Years the resume itself states, e.g. '6 years of experience'.")
    required_years: float | None
    relevant_roles: list[str]
    gaps: list[str]
    responsibility_alignment: int | None
    seniority: SeniorityAlignment


class QualificationsAnalysis(BaseModel):
    education_matched: list[SkillRef]
    education_missing: list[SkillRef]
    certifications_matched: list[SkillRef]
    certifications_missing: list[SkillRef]


class KeywordAnalysis(BaseModel):
    present: list[str]
    missing: list[str]
    coverage: int | None = Field(description="Percent of job keywords found in the resume.")


RecommendationKind = Literal["provide_evidence", "develop_skill", "present_better", "clarify_experience", "keyword"]


class MatchRecommendation(BaseModel):
    kind: RecommendationKind
    requirement_id: str | None
    message: str
    impact: float = Field(description="Approximate match-percentage points recoverable if fully addressed.")


class MatchRecommendations(BaseModel):
    top: list[MatchRecommendation]
    skills_to_develop: list[str]
    present_better: list[str]
    missing_evidence: list[str]


class SemanticInfo(BaseModel):
    status: SemanticStatus
    model: str | None = None
    reason: str | None = None
    related_threshold: float
    text_threshold: float


class Confidence(BaseModel):
    level: Literal["high", "medium", "low"]
    evidence_coverage: int = Field(description="Percent of requirements with any supporting resume evidence.")
    reasons: list[str]


class Methodology(BaseModel):
    version: str
    formula: str
    weights: dict[str, int]
    credits: dict[str, float]
    thresholds: dict[str, float]
    notes: list[str]


class MatchReport(BaseModel):
    matching_version: str
    match_score: int = Field(ge=0, le=100)
    label: str
    classification: str = Field(description="Plain-language classification of the match.")
    score_cap: str | None = None
    components: list[ComponentScore]
    requirements: list[RequirementResult]
    skills: SkillsAnalysis
    experience: ExperienceAnalysis
    qualifications: QualificationsAnalysis
    keywords: KeywordAnalysis
    recommendations: MatchRecommendations
    semantic: SemanticInfo
    confidence: Confidence
    methodology: Methodology
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = MATCH_DISCLAIMER


class SemanticPair(BaseModel):
    """Best embedding similarity found for one requirement (stored with the match for reproducibility)."""

    resume_text: str
    similarity: float


class SemanticSignals(BaseModel):
    status: SemanticStatus
    model: str | None = None
    reason: str | None = None
    skill_pairs: dict[str, SemanticPair] = Field(default_factory=dict)
    text_pairs: dict[str, SemanticPair] = Field(default_factory=dict)

    def as_inputs(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
