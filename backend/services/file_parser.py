"""Extract raw text from uploaded resume/JD files (.pdf, .md)."""

import io
from pathlib import Path

from fastapi import UploadFile
from pypdf import PdfReader

ALLOWED_EXTENSIONS = {".pdf", ".md"}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


class FileParserError(Exception):
    """Raised when an uploaded file fails validation or cannot be parsed."""


async def extract_text(upload: UploadFile) -> str:
    """Validate an uploaded file's type/size and return its extracted text.

    Raises FileParserError on an unsupported type, an oversized/empty file, or
    a file with no extractable text.
    """

    extension = Path(upload.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise FileParserError(
            f"Unsupported file type '{extension or 'unknown'}'. Only .pdf and .md files are accepted."
        )

    contents = await upload.read()
    if not contents:
        raise FileParserError("Uploaded file is empty.")
    if len(contents) > MAX_FILE_SIZE_BYTES:
        raise FileParserError("File is too large. Maximum allowed size is 5MB.")

    if extension == ".pdf":
        return _extract_pdf_text(contents)
    return _extract_markdown_text(contents)


def _extract_pdf_text(contents: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(contents))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001 - surface any pypdf parsing failure uniformly
        raise FileParserError(f"Could not read PDF file: {exc}") from exc

    text = text.strip()
    if not text:
        raise FileParserError("No extractable text found in PDF file.")
    return text


def _extract_markdown_text(contents: bytes) -> str:
    try:
        text = contents.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileParserError("Markdown file must be UTF-8 encoded.") from exc

    text = text.strip()
    if not text:
        raise FileParserError("Markdown file is empty.")
    return text
