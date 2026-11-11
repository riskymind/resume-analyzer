"""Builders for rewrite tests: the sample resume and job run through the real verified extraction pipeline."""

from __future__ import annotations

from datetime import date

from app.parsing.normalize import normalize_text
from app.parsing.sections import detect_sections
from app.schemas.job import StructuredJob
from app.schemas.matching import SemanticSignals
from app.schemas.resume import AIResumeExtraction, StructuredResume
from app.schemas.rewrite import ResumeDocument
from app.services.extraction import build_structured_resume
from app.services.job_extraction import extract_structured_job
from app.services.matching.engine import match_resume_to_job
from app.services.rewriting.document import build_document
from app.services.rewriting.generator import JobContext
from app.services.rewriting.verification import VerificationContext
from tests.fixtures.documents import SAMPLE_EXTRACTION, SAMPLE_JD, SAMPLE_RESUME_MD

AS_OF = date(2026, 11, 8)
RESUME_TEXT = normalize_text(SAMPLE_RESUME_MD)


def sample_structured() -> StructuredResume:
    raw = AIResumeExtraction.model_validate(SAMPLE_EXTRACTION)
    return build_structured_resume(raw, text=RESUME_TEXT, layout=detect_sections(RESUME_TEXT), provider_name="fake")


def sample_document() -> ResumeDocument:
    return build_document(sample_structured(), RESUME_TEXT)


def sample_job() -> StructuredJob:
    from tests.conftest import FakeLLM

    return extract_structured_job(FakeLLM(), text=normalize_text(SAMPLE_JD))


def sample_job_context() -> JobContext:
    job = sample_job()
    report = match_resume_to_job(sample_structured(), RESUME_TEXT, job, SemanticSignals(status="disabled"), as_of=AS_OF)
    return JobContext(job_id="job-1", job=job, report=report)


def sample_context(*, with_job: bool = True) -> VerificationContext:
    return VerificationContext(
        original=sample_document(), resume_text=RESUME_TEXT, job=sample_job() if with_job else None
    )
