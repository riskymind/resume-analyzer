"""Job description pipeline: validate input -> extract text -> AI extraction (verified) -> persist."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import BinaryIO

from app.ai.base import AIProvider
from app.core.config import Settings
from app.core.errors import AppError, InvalidFileError
from app.parsing.files import read_document
from app.parsing.normalize import alnum_count, normalize_text
from app.schemas.job import StructuredJob
from app.services.job_extraction import extract_structured_job


@dataclass(frozen=True)
class JobInput:
    text: str
    source: str  # "pasted" or the uploaded filename
    source_format: str  # text | pdf | docx | markdown
    content_sha256: str


@dataclass(frozen=True)
class JobUpload:
    filename: str | None
    content_type: str | None
    stream: BinaryIO


def read_job_input(
    *, text: str | None, upload: JobUpload | None, settings: Settings, enforce_minimum: bool = True
) -> JobInput:
    """Validate a pasted or uploaded job description. Exactly one source must be provided."""

    has_text = bool(text and text.strip())
    if has_text == (upload is not None):
        raise AppError("Provide the job description as either pasted text or a file, not both or neither.")

    if upload is not None:
        try:
            document = read_document(
                filename=upload.filename,
                content_type=upload.content_type,
                stream=upload.stream,
                max_bytes=settings.max_upload_bytes,
                max_pdf_pages=settings.max_pdf_pages,
            )
        except InvalidFileError as exc:
            raise InvalidFileError(f"Job description file error: {exc.message}") from exc
        if document.format == "pdf" and alnum_count(document.text) < settings.min_job_description_chars:
            raise InvalidFileError(
                "Job description file error: too little text could be extracted from this PDF. It may be a scanned "
                "image; paste the text instead."
            )
        job = JobInput(document.text, upload.filename or "uploaded", document.format, document.content_sha256)
    else:
        assert text is not None
        normalised = normalize_text(text)
        job = JobInput(normalised, "pasted", "text", hashlib.sha256(normalised.encode()).hexdigest())

    if len(job.text) > settings.max_job_description_chars:
        raise AppError(
            f"The job description has {len(job.text):,} characters; the maximum is "
            f"{settings.max_job_description_chars:,}."
        )
    if enforce_minimum and alnum_count(job.text) < settings.min_job_description_chars:
        raise AppError("The job description is too short to analyse. Paste the full posting.")
    return job


def extract_job(provider: AIProvider, job: JobInput) -> StructuredJob:
    return extract_structured_job(provider, text=job.text)
