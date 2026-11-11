"""Upload validation and text extraction for PDF, DOCX and Markdown.

Validation never trusts the filename alone: the extension selects the expected
format, then the file's leading bytes (signature) and the declared MIME type
must agree with it before any parser runs. Error messages are fixed strings;
parser exception text is never echoed to clients.

All formats produce an :class:`ExtractedDocument` whose ``text`` has been
normalised by :func:`app.parsing.normalize.normalize_text`.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Literal

from pypdf import PdfReader

from app.core.errors import InvalidFileError
from app.parsing.docx import extract_docx, looks_like_docx
from app.parsing.normalize import alnum_count, normalize_text

logger = logging.getLogger(__name__)

_GENERIC_MIMES = frozenset({"", "application/octet-stream"})

FormatName = Literal["pdf", "docx", "markdown"]


@dataclass(frozen=True)
class FileFormat:
    name: FormatName
    extension: str
    label: str
    mime_types: frozenset[str]


PDF = FileFormat("pdf", ".pdf", "PDF", frozenset({"application/pdf", "application/x-pdf"}))
DOCX = FileFormat(
    "docx",
    ".docx",
    "Word (.docx)",
    frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"}),
)
MARKDOWN = FileFormat("markdown", ".md", "Markdown", frozenset({"text/markdown", "text/x-markdown", "text/plain"}))

SUPPORTED_FORMATS: dict[str, FileFormat] = {fmt.extension: fmt for fmt in (PDF, DOCX, MARKDOWN)}


@dataclass
class ExtractedDocument:
    format: FormatName
    text: str
    page_count: int | None = None
    pages_without_text: list[int] = field(default_factory=list)
    table_count: int = 0
    styled_heading_count: int = 0
    contact_in_page_header: bool = False
    page_header_text: str = ""  # DOCX page-header parts only
    body_text: str = ""  # DOCX body only (empty for other formats)
    warnings: list[str] = field(default_factory=list)
    content_sha256: str = ""


def supported_extensions_text() -> str:
    names = sorted(SUPPORTED_FORMATS)
    return ", ".join(names[:-1]) + " and " + names[-1]


def read_limited(stream: BinaryIO, max_bytes: int) -> bytes:
    """Read at most ``max_bytes`` (+1 to detect overflow) from an upload stream."""

    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise InvalidFileError(f"File is too large. Maximum allowed size is {max_bytes // (1024 * 1024)}MB.")
    return data


def detect_format(filename: str | None, content_type: str | None, data: bytes) -> FileFormat:
    extension = Path(filename or "").suffix.lower()
    fmt = SUPPORTED_FORMATS.get(extension)
    if fmt is None:
        hint = " Save .doc files as .docx first." if extension == ".doc" else ""
        raise InvalidFileError(
            f"Unsupported file type '{extension or 'unknown'}'. "
            f"Only {supported_extensions_text()} files are accepted.{hint}"
        )
    if not data:
        raise InvalidFileError("Uploaded file is empty.")

    declared = (content_type or "").split(";")[0].strip().lower()
    if declared not in _GENERIC_MIMES and declared not in fmt.mime_types:
        raise InvalidFileError(f"File content type '{declared}' does not match a {fmt.label} file.")

    if not _signature_matches(fmt, data):
        raise InvalidFileError(f"File content does not look like a valid {fmt.label} file.")
    return fmt


def _signature_matches(fmt: FileFormat, data: bytes) -> bool:
    if fmt is PDF:
        # The PDF header may be preceded by junk bytes; readers accept it within the first 1 KiB.
        return b"%PDF-" in data[:1024]
    if fmt is DOCX:
        return looks_like_docx(data)
    if fmt is MARKDOWN:
        return b"\x00" not in data[:8192]
    return False


def extract_document(fmt: FileFormat, data: bytes, *, max_pdf_pages: int) -> ExtractedDocument:
    if fmt is PDF:
        return _extract_pdf(data, max_pages=max_pdf_pages)
    if fmt is DOCX:
        content = extract_docx(data)
        document = ExtractedDocument(
            format="docx",
            text=normalize_text(content.text),
            table_count=content.table_count,
            styled_heading_count=content.heading_count,
            contact_in_page_header=content.header_text_found,
            page_header_text=normalize_text(content.page_header_text),
            body_text=normalize_text(content.body_text),
            warnings=list(content.warnings),
        )
        _require_text(document, "DOCX")
        return document
    return _extract_markdown(data)


def read_document(
    *,
    filename: str | None,
    content_type: str | None,
    stream: BinaryIO,
    max_bytes: int,
    max_pdf_pages: int,
) -> ExtractedDocument:
    data = read_limited(stream, max_bytes)
    fmt = detect_format(filename, content_type, data)
    document = extract_document(fmt, data, max_pdf_pages=max_pdf_pages)
    document.content_sha256 = hashlib.sha256(data).hexdigest()
    return document


def validate_and_extract(
    *,
    filename: str | None,
    content_type: str | None,
    stream: BinaryIO,
    max_bytes: int,
    max_pdf_pages: int,
) -> str:
    """Plain-text variant used for job-description files."""

    return read_document(
        filename=filename,
        content_type=content_type,
        stream=stream,
        max_bytes=max_bytes,
        max_pdf_pages=max_pdf_pages,
    ).text


def ensure_sufficient_resume_text(document: ExtractedDocument, *, min_pdf_chars: int) -> None:
    """Reject documents whose extracted text is too thin to be a real resume.

    PDFs are the case that matters: a scanned resume is a valid PDF whose text
    layer is empty or contains only page numbers. Such files are rejected with
    an actionable message instead of being "analysed" as an empty resume.
    """

    if document.format == "pdf":
        pages = document.page_count or 1
        if alnum_count(document.text) < max(min_pdf_chars, 20 * pages):
            raise InvalidFileError(
                "Too little text could be extracted from this PDF. It looks like a scanned or image-only "
                "document. Export your resume as a text-based PDF or DOCX (for example, File > Save As > PDF "
                "in your word processor) and upload it again."
            )


def _require_text(document: ExtractedDocument, label: str) -> None:
    if not document.text:
        raise InvalidFileError(f"No extractable text found in {label} file.")


def _extract_pdf(data: bytes, *, max_pages: int) -> ExtractedDocument:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except Exception as exc:
        logger.info("pdf_open_failed", extra={"error_type": type(exc).__name__})
        raise InvalidFileError("Could not read PDF file. It may be corrupted.") from exc

    if reader.is_encrypted:
        try:
            unlocked = bool(reader.decrypt(""))
        except Exception:
            unlocked = False
        if not unlocked:
            raise InvalidFileError("PDF is password-protected. Remove the password and upload it again.")

    try:
        page_count = len(reader.pages)
    except Exception as exc:
        logger.info("pdf_pages_failed", extra={"error_type": type(exc).__name__})
        raise InvalidFileError("Could not read PDF file. It may be corrupted.") from exc

    if page_count == 0:
        raise InvalidFileError("PDF file has no pages.")
    if page_count > max_pages:
        raise InvalidFileError(f"PDF has {page_count} pages; the maximum is {max_pages}.")

    page_texts: list[str] = []
    try:
        for page in reader.pages:
            page_texts.append(normalize_text(page.extract_text() or ""))
    except Exception as exc:
        logger.info("pdf_extract_failed", extra={"error_type": type(exc).__name__})
        raise InvalidFileError("Could not read PDF file. It may be corrupted.") from exc

    text = "\n\n".join(t for t in page_texts if t).strip()
    if not text:
        raise InvalidFileError(
            "No extractable text found in PDF file. Scanned/image-only PDFs are not supported; "
            "export a text-based PDF or DOCX instead."
        )

    empty_pages = [index + 1 for index, page_text in enumerate(page_texts) if alnum_count(page_text) < 20]
    document = ExtractedDocument(format="pdf", text=text, page_count=page_count, pages_without_text=empty_pages)
    if empty_pages and len(empty_pages) < page_count:
        listed = ", ".join(map(str, empty_pages))
        document.warnings.append(
            f"Page(s) {listed} contain little or no selectable text (possibly scanned images); "
            "their content could not be analysed."
        )
    return document


def _extract_markdown(data: bytes) -> ExtractedDocument:
    try:
        raw = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidFileError("Markdown file must be UTF-8 encoded.") from exc
    text = normalize_text(raw)
    if not text:
        raise InvalidFileError("Markdown file is empty.")
    return ExtractedDocument(format="markdown", text=text)
