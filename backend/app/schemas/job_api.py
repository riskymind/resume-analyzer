"""Request/response schemas for /api/v1/jobs and /api/v1/matches."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.job import JobExtractionInfo, JobInfo, JobKeyword, JobRequirement
from app.schemas.matching import MatchReport


class JobSummary(BaseModel):
    id: str
    title: str | None
    company: str | None
    source: str
    source_format: str
    created_at: datetime
    requirement_count: int
    match_count: int


class JobDetail(JobSummary):
    text: str
    info: JobInfo
    requirements: list[JobRequirement]
    keywords: list[JobKeyword]
    extraction: JobExtractionInfo
    warnings: list[str]


class MatchCreate(BaseModel):
    resume_id: str = Field(min_length=1, max_length=36)
    job_id: str = Field(min_length=1, max_length=36)


class MatchSummary(BaseModel):
    id: str
    resume_id: str
    job_id: str
    resume_filename: str
    job_title: str | None
    match_score: int
    label: str
    semantic_status: str
    matching_version: str
    created_at: datetime


class MatchDetail(MatchSummary):
    report: MatchReport
