"""Resume rewriting schemas.

Three layers:

- :class:`ResumeDocument` - the editable, exportable resume. Plain values with
  stable ids (``exp-1``, ``exp-1-b2``, ``proj-1``...) so every rewritten item
  can be traced to the original item it came from.
- :class:`Suggestion` - one AI proposal for one unit of the document, with its
  verification result and the user's decision.
- ``AIRewrite*`` - exactly what the model is asked to return. Nothing in them
  is trusted: the model refers to items by id and only supplies wording.
  Employers, titles, dates, degrees and certifications are never part of the
  model's output; application code copies them from the original.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------- document

_ID = r"^[A-Za-z0-9_-]{1,40}$"
_SHORT = 300
_LONG = 2000
_BULLET = 600


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocLink(_Strict):
    kind: Literal["linkedin", "github", "website"]
    url: str = Field(max_length=500)

    @field_validator("url")
    @classmethod
    def _http_only(cls, value: str) -> str:
        value = value.strip()
        # Exported documents make links clickable; only web links are allowed
        # (no javascript:, file: or data: URLs).
        if not re.match(r"^https?://[^\s<>\"']+$", value, re.IGNORECASE):
            raise ValueError("Links must be http(s) URLs.")
        return value


class DocContact(_Strict):
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=_SHORT)
    links: list[DocLink] = Field(default_factory=list, max_length=10)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str | None) -> str | None:
        if value and not re.fullmatch(r"[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+", value.strip()):
            raise ValueError("Enter a valid email address.")
        return value.strip() if value else value


class DocBullet(_Strict):
    id: str = Field(pattern=_ID)
    text: str = Field(max_length=_BULLET)
    # Ids of the original bullets this one is based on. Empty for bullets the user added.
    source_ids: list[str] = Field(default_factory=list, max_length=20)


class DocExperience(_Strict):
    id: str = Field(pattern=_ID)
    title: str | None = Field(default=None, max_length=_SHORT)
    employer: str | None = Field(default=None, max_length=_SHORT)
    location: str | None = Field(default=None, max_length=_SHORT)
    start_date: str | None = Field(default=None, max_length=40)
    end_date: str | None = Field(default=None, max_length=40)
    bullets: list[DocBullet] = Field(default_factory=list, max_length=40)


class DocEducation(_Strict):
    id: str = Field(pattern=_ID)
    institution: str | None = Field(default=None, max_length=_SHORT)
    qualification: str | None = Field(default=None, max_length=_SHORT)
    field_of_study: str | None = Field(default=None, max_length=_SHORT)
    start_date: str | None = Field(default=None, max_length=40)
    end_date: str | None = Field(default=None, max_length=40)
    grade: str | None = Field(default=None, max_length=80)
    # Relevant coursework. Not produced by the AI extraction; added by the user and verified against the
    # original resume text (courses it does not mention are flagged as unsupported user claims).
    coursework: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("coursework")
    @classmethod
    def _course_lengths(cls, values: list[str]) -> list[str]:
        if any(len(value) > 120 for value in values):
            raise ValueError("Course names must be 120 characters or fewer.")
        return [value.strip() for value in values if value.strip()]


class DocCertification(_Strict):
    id: str = Field(pattern=_ID)
    name: str | None = Field(default=None, max_length=_SHORT)
    issuer: str | None = Field(default=None, max_length=_SHORT)
    date: str | None = Field(default=None, max_length=40)


class DocProject(_Strict):
    id: str = Field(pattern=_ID)
    name: str | None = Field(default=None, max_length=_SHORT)
    description: str | None = Field(default=None, max_length=_LONG)
    technologies: list[str] = Field(default_factory=list, max_length=40)


class DocLanguage(_Strict):
    name: str = Field(max_length=80)
    proficiency: str | None = Field(default=None, max_length=80)


class ResumeDocument(_Strict):
    """An editable resume. Also the request body when the user saves edits."""

    contact: DocContact = Field(default_factory=DocContact)
    summary: str | None = Field(default=None, max_length=_LONG)
    experience: list[DocExperience] = Field(default_factory=list, max_length=40)
    education: list[DocEducation] = Field(default_factory=list, max_length=20)
    certifications: list[DocCertification] = Field(default_factory=list, max_length=40)
    projects: list[DocProject] = Field(default_factory=list, max_length=40)
    technical_skills: list[str] = Field(default_factory=list, max_length=150)
    soft_skills: list[str] = Field(default_factory=list, max_length=60)
    languages: list[DocLanguage] = Field(default_factory=list, max_length=20)

    @field_validator("technical_skills", "soft_skills")
    @classmethod
    def _skill_lengths(cls, values: list[str]) -> list[str]:
        if any(len(value) > 80 for value in values):
            raise ValueError("Skill names must be 80 characters or fewer.")
        return [value.strip() for value in values if value.strip()]

    @model_validator(mode="after")
    def _unique_ids(self) -> ResumeDocument:
        ids: list[str] = []
        for entry in self.experience:
            ids.append(entry.id)
            ids.extend(bullet.id for bullet in entry.bullets)
        ids += [e.id for e in self.education] + [c.id for c in self.certifications] + [p.id for p in self.projects]
        if len(ids) != len(set(ids)):
            raise ValueError("Item ids must be unique within a resume.")
        return self

    def is_empty(self) -> bool:
        return not (
            self.contact.name
            or (self.summary and self.summary.strip())
            or any(e.title or e.employer or e.bullets for e in self.experience)
            or self.education
            or self.certifications
            or self.projects
            or self.technical_skills
            or self.soft_skills
        )


# --------------------------------------------------------------------------- requests / options

RewriteScope = Literal[
    "full",  # every rewritable section
    "summary",
    "experience",
    "bullets",  # selected experience bullets only
    "skills",
    "projects",
    "education",  # education and certifications: ordering and presentation only
    "keywords",  # targeted keyword optimisation (needs a job description)
]
RewriteMode = Literal["professional", "ats", "job_targeted", "executive"]
TemplateKey = Literal["modern", "minimal", "corporate", "technical", "graduate"]
ExportFormat = Literal["pdf", "docx"]

SCOPE_SECTIONS: dict[str, tuple[str, ...]] = {
    "full": ("summary", "experience", "skills", "projects", "education"),
    "summary": ("summary",),
    "experience": ("experience",),
    "bullets": ("experience",),
    "skills": ("skills",),
    "projects": ("projects",),
    "education": ("education",),
    "keywords": ("summary", "experience", "skills"),
}

Section = Literal["summary", "experience", "skills", "projects", "education", "certifications"]


class RewriteCreate(BaseModel):
    resume_id: str = Field(min_length=1, max_length=36)
    job_id: str | None = Field(default=None, min_length=1, max_length=36)
    scope: RewriteScope = "full"
    mode: RewriteMode | None = None
    bullet_ids: list[str] = Field(default_factory=list, max_length=40)
    name: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _consistent(self) -> RewriteCreate:
        _check_scope(self.scope, self.bullet_ids, self.mode, has_job=self.job_id is not None)
        return self


class RegenerateRequest(BaseModel):
    scope: RewriteScope
    mode: RewriteMode | None = None
    bullet_ids: list[str] = Field(default_factory=list, max_length=40)
    base_version: int = Field(ge=1, description="The version the client is looking at (optimistic concurrency).")


def _check_scope(scope: str, bullet_ids: list[str], mode: str | None, *, has_job: bool | None) -> None:
    if scope == "bullets" and not bullet_ids:
        raise ValueError("Select at least one bullet to rewrite.")
    if scope != "bullets" and bullet_ids:
        raise ValueError("bullet_ids is only used with the 'bullets' scope.")
    if any(not re.fullmatch(_ID, bullet_id) for bullet_id in bullet_ids):
        raise ValueError("Invalid bullet id.")
    if has_job is False and scope == "keywords":
        raise ValueError("Keyword optimisation needs a job description.")
    if has_job is False and mode == "job_targeted":
        raise ValueError("A job-targeted rewrite needs a job description.")


Decision = Literal["pending", "accepted", "rejected"]


class RewriteUpdate(BaseModel):
    """Exactly one kind of change per request (plus optional metadata)."""

    base_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    template: TemplateKey | None = None
    content: ResumeDocument | None = None
    decisions: dict[str, Literal["accepted", "rejected"]] | None = Field(default=None, max_length=200)
    restore_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _one_change(self) -> RewriteUpdate:
        changes = [self.content is not None, self.decisions is not None, self.restore_version is not None]
        if sum(changes) > 1:
            raise ValueError("Send content, decisions or restore_version, not more than one.")
        if not any(changes) and self.name is None and self.template is None:
            raise ValueError("Nothing to update.")
        return self


class ExportRequest(BaseModel):
    format: ExportFormat
    template: TemplateKey | None = None
    version: int | None = Field(default=None, ge=1)
    acknowledge_unverified: bool = Field(
        default=False,
        description="Required when the exported version contains claims that could not be verified against the "
        "original resume (blocking or warning issues). Confirms the user has reviewed them.",
    )


# --------------------------------------------------------------------------- verification

Severity = Literal["blocking", "warning", "info"]
Origin = Literal["ai", "user"]


class VerificationIssue(BaseModel):
    code: str
    severity: Severity
    message: str
    term: str | None = Field(default=None, description="The unsupported value, e.g. '45%' or 'Kubernetes'.")
    unit: str | None = Field(default=None, description="Document unit, e.g. 'summary' or 'experience:exp-1'.")
    item_id: str | None = None
    origin: Origin = "ai"
    action: Literal["flagged", "removed"] = "flagged"


class SuggestionVerification(BaseModel):
    status: Literal["verified", "warning", "rejected"]
    issues: list[VerificationIssue] = Field(default_factory=list)


class VerificationSummary(BaseModel):
    """Verification of the saved content (AI suggestions that were applied, plus any manual edits)."""

    status: Literal["verified", "needs_review", "unsupported"]
    blocking: int
    warnings: int
    issues: list[VerificationIssue]
    rejected_suggestions: int
    pending_review: int = Field(description="Suggestions with warnings the user has not accepted or rejected.")
    checks: list[str] = Field(description="Plain-language list of the checks applied.")


# --------------------------------------------------------------------------- suggestions


class Suggestion(BaseModel):
    id: str
    unit: str = Field(description="'summary', 'experience:<id>', 'skills', 'project:<id>', 'education', ...")
    section: Section
    item_id: str | None = None
    kind: Literal["text", "bullet", "skills", "order"]
    original: str | None = Field(description="The original wording (bullets it replaces, joined by newlines).")
    proposed: str = Field(description="The proposed wording, or a readable rendering of a list/order change.")
    source_ids: list[str] = Field(default_factory=list)
    technical: list[str] | None = None
    soft: list[str] | None = None
    order: list[str] | None = None
    rationale: str | None = None
    keywords: list[str] = Field(default_factory=list, description="Job keywords the proposal actually contains.")
    requirement_ids: list[str] = Field(default_factory=list)
    metric_prompt: str | None = Field(default=None, description="A question for the user; never a number.")
    verification: SuggestionVerification
    decision: Decision = "pending"
    auto_rejected: bool = False
    generation: int = Field(default=1, description="Which generation (create = 1, regenerations +1) produced it.")

    @property
    def applied(self) -> bool:
        """Applied to the content: accepted, or pending and verified without warnings."""

        if self.verification.status == "rejected":
            return False
        return self.decision == "accepted" or (self.decision == "pending" and self.verification.status == "verified")


# --------------------------------------------------------------------------- generation metadata


class Gap(BaseModel):
    requirement_id: str
    name: str
    category: str
    classification: str
    message: str


class MetricPrompt(BaseModel):
    item_id: str
    bullet: str
    question: str


class GenerationInfo(BaseModel):
    generation: int
    scope: RewriteScope
    mode: RewriteMode
    bullet_ids: list[str] = Field(default_factory=list)
    provider: str
    prompt_version: str
    alignment_notes: list[str] = Field(
        default_factory=list, description="The model's short explanation of how the rewrite targets the job."
    )
    gaps: list[Gap] = Field(default_factory=list)
    metric_prompts: list[MetricPrompt] = Field(default_factory=list)
    discarded_items: int = Field(default=0, description="Model output items dropped as malformed or out of scope.")
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- scores

SCORE_DISCLAIMER = (
    "Both scores are recalculated by the same deterministic rules from the saved content. A higher score means "
    "the resume reads better against those rules or evidences more of the job's stated requirements; it does not "
    "guarantee an interview or predict any employer's decision."
)


class QualityComparison(BaseModel):
    before: int
    after: int
    before_ats: int
    after_ats: int
    before_label: str
    after_label: str
    uploaded_score: int | None = Field(
        description="Score of the originally uploaded file. It can differ from 'before', which scores the "
        "extracted content in the same export layout as the rewrite so the comparison is like for like."
    )


class MatchComparison(BaseModel):
    job_id: str
    job_title: str | None
    before: int
    after: int
    before_label: str
    after_label: str
    newly_evidenced: list[str] = Field(description="Requirements with more resume evidence after the rewrite.")
    still_missing: list[str]
    saved_match_score: int | None = Field(description="Latest saved match for this resume and job, if any.")
    method: str


class ScoreComparison(BaseModel):
    quality: QualityComparison
    match: MatchComparison | None = None
    keywords_incorporated: list[str] = Field(default_factory=list)
    disclaimer: str = SCORE_DISCLAIMER


# --------------------------------------------------------------------------- API responses


class TemplateInfo(BaseModel):
    key: TemplateKey
    name: str
    description: str


class VersionSummary(BaseModel):
    number: int
    source: Literal["generate", "regenerate", "decisions", "edit", "restore"]
    created_at: datetime
    quality_after: int
    match_after: int | None
    verification_status: str


class RewriteSummary(BaseModel):
    id: str
    name: str
    resume_id: str
    resume_filename: str
    job_id: str | None
    job_title: str | None
    mode: RewriteMode
    template: TemplateKey
    current_version: int
    quality_before: int | None
    quality_after: int | None
    match_before: int | None
    match_after: int | None
    verification_status: str | None
    job_detached_at: datetime | None = Field(
        default=None,
        description="Set when the target job was deleted: the rewrite is kept, but job-derived scores, gaps, "
        "keywords and analysis were removed from it.",
    )
    created_at: datetime
    updated_at: datetime


class RewriteDetail(RewriteSummary):
    version: int = Field(description="The version shown (the current one unless another was requested).")
    original: ResumeDocument
    content: ResumeDocument
    suggestions: list[Suggestion]
    verification: VerificationSummary
    scores: ScoreComparison
    generation: GenerationInfo
    versions: list[VersionSummary]


class PreviewResponse(BaseModel):
    template: TemplateKey
    version: int
    html: str


# --------------------------------------------------------------------------- model output (untrusted)


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AIRewriteText(_Lenient):
    text: str = Field(max_length=_LONG)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    requirement_ids: list[str] = Field(default_factory=list, max_length=30)
    rationale: str | None = Field(default=None, max_length=500)


class AIRewriteBullet(_Lenient):
    text: str = Field(max_length=_BULLET)
    source_ids: list[str] = Field(default_factory=list, max_length=10)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    requirement_ids: list[str] = Field(default_factory=list, max_length=30)
    rationale: str | None = Field(default=None, max_length=500)
    metric_prompt: str | None = Field(default=None, max_length=300)


class AIRewriteRole(_Lenient):
    id: str = Field(max_length=40)
    bullets: list[AIRewriteBullet] = Field(default_factory=list, max_length=40)


class AIRewriteProject(_Lenient):
    id: str = Field(max_length=40)
    description: str = Field(max_length=_LONG)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    requirement_ids: list[str] = Field(default_factory=list, max_length=30)
    rationale: str | None = Field(default=None, max_length=500)


class AIRewriteSkills(_Lenient):
    technical: list[str] = Field(default_factory=list, max_length=150)
    soft: list[str] = Field(default_factory=list, max_length=60)
    rationale: str | None = Field(default=None, max_length=500)


class AIRewriteOutput(_Lenient):
    """Exactly what the model is asked to return. Nothing here is trusted."""

    summary: AIRewriteText | None = None
    experience: list[AIRewriteRole] = Field(default_factory=list, max_length=40)
    skills: AIRewriteSkills | None = None
    projects: list[AIRewriteProject] = Field(default_factory=list, max_length=40)
    education_order: list[str] | None = Field(default=None, max_length=20)
    certification_order: list[str] | None = Field(default=None, max_length=40)
    alignment_notes: list[str] = Field(default_factory=list, max_length=10)
