"""Resume pipeline: parse -> detect sections -> AI extraction (verified) -> deterministic score -> persist.

Parsing and scoring are deterministic. The single AI step happens before
anything is written, and persistence happens in the caller's transaction, so
an AI failure leaves no partial resume behind.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.ai.base import AIProvider
from app.core.config import Settings
from app.core.errors import InvalidFileError
from app.db.models import Resume, ResumeAnalysis
from app.parsing.files import ExtractedDocument, ensure_sufficient_resume_text, read_document
from app.parsing.sections import DocumentLayout, detect_sections
from app.repositories import resumes as resumes_repo
from app.schemas.resume import StructuredResume
from app.schemas.scoring import QualityReport
from app.services.extraction import extract_structured_resume
from app.services.scoring.config import DEFAULT_CONFIG, ScoringConfig
from app.services.scoring.engine import ScoringInput, score_resume

logger = logging.getLogger(__name__)


@dataclass
class ParsedResume:
    filename: str
    document: ExtractedDocument
    layout: DocumentLayout


@dataclass
class ProcessedResume:
    parsed: ParsedResume
    structured: StructuredResume
    report: QualityReport


def parse_resume(
    *, filename: str | None, content_type: str | None, stream: BinaryIO, settings: Settings
) -> ParsedResume:
    """Validate, extract and check the upload. Deterministic; raises InvalidFileError on bad input."""

    document = read_document(
        filename=filename,
        content_type=content_type,
        stream=stream,
        max_bytes=settings.max_upload_bytes,
        max_pdf_pages=settings.max_pdf_pages,
    )
    ensure_sufficient_resume_text(document, min_pdf_chars=settings.min_pdf_text_chars)
    if len(document.text) > settings.max_resume_chars:
        raise InvalidFileError(
            f"The resume contains {len(document.text):,} characters of text; the maximum is "
            f"{settings.max_resume_chars:,}. Upload a shorter resume (two pages is typical)."
        )
    return ParsedResume(filename=filename or "resume", document=document, layout=detect_sections(document.text))


def analyse_resume(
    parsed: ParsedResume, provider: AIProvider, *, config: ScoringConfig = DEFAULT_CONFIG
) -> ProcessedResume:
    structured = extract_structured_resume(provider, text=parsed.document.text, layout=parsed.layout)
    if parsed.document.warnings:
        structured.extraction.warnings = [*parsed.document.warnings, *structured.extraction.warnings]
    report = score_resume(ScoringInput(document=parsed.document, layout=parsed.layout, structured=structured), config)
    return ProcessedResume(parsed=parsed, structured=structured, report=report)


def save_processed_resume(db: Session, *, user_id: str, processed: ProcessedResume) -> tuple[Resume, ResumeAnalysis]:
    resume = resumes_repo.create_resume(
        db,
        user_id=user_id,
        filename=processed.parsed.filename,
        document=processed.parsed.document,
        layout=processed.parsed.layout,
        structured=processed.structured,
    )
    analysis = resumes_repo.create_analysis(db, user_id=user_id, resume_id=resume.id, report=processed.report)
    logger.info(
        "resume_saved",
        extra={"resume_id": resume.id, "overall_score": processed.report.overall_score, "format": resume.file_format},
    )
    return resume, analysis
