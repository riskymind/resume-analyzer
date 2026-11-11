"""Request/response schemas for /api/v1/resumes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.resume import StructuredResume
from app.schemas.scoring import QualityReport


class SectionOut(BaseModel):
    kind: str
    heading: str


class ResumeSummary(BaseModel):
    id: str
    filename: str
    file_format: str
    created_at: datetime
    overall_score: int | None
    ats_score: int | None
    label: str | None


class ResumeDetail(ResumeSummary):
    page_count: int | None
    warnings: list[str]
    sections: list[SectionOut]
    text: str
    structured: StructuredResume
    quality: QualityReport | None
