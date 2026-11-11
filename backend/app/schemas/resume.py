"""Structured resume schema.

Every extracted value records where it came from:

- ``explicit``  - the value appears verbatim in the resume text;
- ``inferred``  - derived from the resume with a verbatim supporting quote in
  ``evidence`` (only allowed for soft skills, locations, language proficiency
  and the inferred name position);
- ``missing``   - not present or not verifiable; ``value`` is ``None``.

The *status is decided by application code* after checking the source text
(``app.services.extraction``), never by the model's own claim.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["explicit", "inferred", "missing"]


class TextField(BaseModel):
    value: str | None = None
    status: Status = "missing"
    evidence: str | None = None

    @property
    def present(self) -> bool:
        return self.status != "missing" and bool(self.value)


class Link(BaseModel):
    kind: Literal["linkedin", "github", "website"]
    url: str
    status: Status = "explicit"


class Contact(BaseModel):
    name: TextField = Field(default_factory=TextField)
    email: TextField = Field(default_factory=TextField)
    phone: TextField = Field(default_factory=TextField)
    location: TextField = Field(default_factory=TextField)
    links: list[Link] = Field(default_factory=list)


class Bullet(BaseModel):
    text: str
    kind: Literal["responsibility", "achievement"]
    metrics: list[str] = Field(default_factory=list)


class ExperienceEntry(BaseModel):
    title: TextField = Field(default_factory=TextField)
    employer: TextField = Field(default_factory=TextField)
    location: TextField = Field(default_factory=TextField)
    start_date: TextField = Field(default_factory=TextField)
    end_date: TextField = Field(default_factory=TextField)
    is_current: bool | None = None
    responsibilities: list[Bullet] = Field(default_factory=list)
    achievements: list[Bullet] = Field(default_factory=list)

    @property
    def bullets(self) -> list[Bullet]:
        return [*self.achievements, *self.responsibilities]


class Skill(BaseModel):
    name: str
    status: Status
    evidence: str | None = None


class EducationEntry(BaseModel):
    institution: TextField = Field(default_factory=TextField)
    qualification: TextField = Field(default_factory=TextField)
    field_of_study: TextField = Field(default_factory=TextField)
    start_date: TextField = Field(default_factory=TextField)
    end_date: TextField = Field(default_factory=TextField)
    grade: TextField = Field(default_factory=TextField)


class Certification(BaseModel):
    name: TextField = Field(default_factory=TextField)
    issuer: TextField = Field(default_factory=TextField)
    date: TextField = Field(default_factory=TextField)


class Project(BaseModel):
    name: TextField = Field(default_factory=TextField)
    description: TextField = Field(default_factory=TextField)
    technologies: list[str] = Field(default_factory=list)


class Language(BaseModel):
    name: str
    proficiency: TextField = Field(default_factory=TextField)


class ExtractionInfo(BaseModel):
    method: Literal["ai"] = "ai"
    provider: str
    prompt_version: str
    removed_items: int = 0
    warnings: list[str] = Field(default_factory=list)


class StructuredResume(BaseModel):
    contact: Contact = Field(default_factory=Contact)
    summary: TextField = Field(default_factory=TextField)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    technical_skills: list[Skill] = Field(default_factory=list)
    soft_skills: list[Skill] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    extraction: ExtractionInfo


# --------------------------------------------------------------------------- model output (untrusted)

_MAX_TEXT = 2000


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AIValue(_Lenient):
    value: str | None = Field(default=None, max_length=_MAX_TEXT)
    evidence: str | None = Field(default=None, max_length=_MAX_TEXT)


class AIBullet(_Lenient):
    text: str = Field(max_length=_MAX_TEXT)
    type: Literal["responsibility", "achievement"] = "responsibility"


class AIExperience(_Lenient):
    title: AIValue | None = None
    employer: AIValue | None = None
    location: AIValue | None = None
    start_date: AIValue | None = None
    end_date: AIValue | None = None
    bullets: list[AIBullet] = Field(default_factory=list, max_length=60)


class AISkill(_Lenient):
    name: str = Field(max_length=120)
    evidence: str | None = Field(default=None, max_length=_MAX_TEXT)


class AIEducation(_Lenient):
    institution: AIValue | None = None
    qualification: AIValue | None = None
    field_of_study: AIValue | None = None
    start_date: AIValue | None = None
    end_date: AIValue | None = None
    grade: AIValue | None = None


class AICertification(_Lenient):
    name: AIValue | None = None
    issuer: AIValue | None = None
    date: AIValue | None = None


class AIProject(_Lenient):
    name: AIValue | None = None
    description: AIValue | None = None
    technologies: list[str] = Field(default_factory=list, max_length=60)


class AILanguage(_Lenient):
    name: str = Field(max_length=80)
    proficiency: AIValue | None = None


class AIResumeExtraction(_Lenient):
    """Exactly what the model is asked to return. Nothing here is trusted."""

    name: AIValue | None = None
    location: AIValue | None = None
    summary: AIValue | None = None
    experience: list[AIExperience] = Field(default_factory=list, max_length=40)
    education: list[AIEducation] = Field(default_factory=list, max_length=20)
    technical_skills: list[AISkill] = Field(default_factory=list, max_length=150)
    soft_skills: list[AISkill] = Field(default_factory=list, max_length=60)
    certifications: list[AICertification] = Field(default_factory=list, max_length=40)
    projects: list[AIProject] = Field(default_factory=list, max_length=40)
    languages: list[AILanguage] = Field(default_factory=list, max_length=20)
