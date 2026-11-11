"""File validation and extraction: signatures, MIME, size, encrypted/malformed PDFs."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from app.core.errors import InvalidFileError
from app.parsing.files import MARKDOWN, PDF, detect_format, extract_document, read_limited, validate_and_extract
from tests.fixtures.documents import make_blank_pdf, make_pdf


def _pdf_with_pages(count: int, *, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=612, height=792)
    if password is not None:
        writer.encrypt(user_password=password, owner_password=password, algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _extract(filename: str, data: bytes, content_type: str = "", max_bytes: int = 5 * 1024 * 1024) -> str:
    return validate_and_extract(
        filename=filename,
        content_type=content_type,
        stream=io.BytesIO(data),
        max_bytes=max_bytes,
        max_pdf_pages=20,
    )


class TestSignatures:
    def test_pdf_extension_with_text_content_is_rejected(self) -> None:
        with pytest.raises(InvalidFileError, match="does not look like a valid PDF"):
            _extract("resume.pdf", b"just some text pretending to be a pdf")

    def test_executable_renamed_to_pdf_is_rejected(self) -> None:
        with pytest.raises(InvalidFileError, match="does not look like a valid PDF"):
            _extract("resume.pdf", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100)

    def test_markdown_with_binary_content_is_rejected(self) -> None:
        with pytest.raises(InvalidFileError, match="does not look like a valid Markdown"):
            _extract("resume.md", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    def test_valid_pdf_is_accepted(self) -> None:
        assert "Jane Doe" in _extract("resume.pdf", make_pdf("Jane Doe\nEngineer"), "application/pdf")

    def test_extension_is_case_insensitive(self) -> None:
        assert _extract("RESUME.PDF", make_pdf("Jane Doe"), "application/pdf").startswith("Jane")

    def test_markdown_with_bom_is_accepted(self) -> None:
        assert _extract("cv.md", "﻿# Jane".encode()) == "# Jane"


class TestMimeTypes:
    @pytest.mark.parametrize("mime", ["image/png", "text/html", "application/zip"])
    def test_contradicting_mime_is_rejected(self, mime: str) -> None:
        with pytest.raises(InvalidFileError, match="does not match"):
            _extract("resume.pdf", make_pdf("Jane"), mime)

    @pytest.mark.parametrize(
        "mime", ["", "application/octet-stream", "application/pdf", "application/pdf; charset=binary"]
    )
    def test_acceptable_pdf_mimes(self, mime: str) -> None:
        assert detect_format("a.pdf", mime, make_pdf("x")) is PDF

    @pytest.mark.parametrize("mime", ["", "text/markdown", "text/plain", "text/x-markdown"])
    def test_acceptable_markdown_mimes(self, mime: str) -> None:
        assert detect_format("a.md", mime, b"# hi") is MARKDOWN


class TestSize:
    def test_exactly_at_limit_is_allowed(self) -> None:
        assert read_limited(io.BytesIO(b"a" * 10), 10) == b"a" * 10

    def test_one_byte_over_limit_is_rejected(self) -> None:
        with pytest.raises(InvalidFileError, match="too large"):
            read_limited(io.BytesIO(b"a" * 11), 10)

    def test_read_is_bounded(self) -> None:
        class Endless(io.RawIOBase):
            def __init__(self) -> None:
                self.reads: list[int] = []

            def read(self, size: int = -1) -> bytes:
                self.reads.append(size)
                return b"a" * size

        stream = Endless()
        with pytest.raises(InvalidFileError):
            read_limited(stream, 1024)  # type: ignore[arg-type]
        assert stream.reads == [1025]

    @pytest.mark.parametrize("filename", ["resume.md", "resume.pdf"])
    def test_empty_file_is_rejected(self, filename: str) -> None:
        with pytest.raises(InvalidFileError, match="empty"):
            _extract(filename, b"")


class TestPdfEdgeCases:
    def test_password_protected_pdf_is_rejected_clearly(self) -> None:
        with pytest.raises(InvalidFileError, match="password-protected"):
            extract_document(PDF, _pdf_with_pages(1, password="secret"), max_pdf_pages=20)

    def test_page_limit(self) -> None:
        with pytest.raises(InvalidFileError, match="21 pages; the maximum is 20"):
            extract_document(PDF, _pdf_with_pages(21), max_pdf_pages=20)

    def test_image_only_pdf_explains_scans_are_unsupported(self) -> None:
        with pytest.raises(InvalidFileError, match="Scanned/image-only"):
            extract_document(PDF, make_blank_pdf(), max_pdf_pages=20)

    def test_truncated_pdf_is_rejected_without_leaking_parser_details(self) -> None:
        data = make_pdf("Jane Doe")[:60]
        with pytest.raises(InvalidFileError) as exc_info:
            extract_document(PDF, data, max_pdf_pages=20)
        assert "Traceback" not in exc_info.value.message
        assert exc_info.value.message.startswith(("Could not read PDF", "No extractable text", "PDF file has no pages"))

    def test_unsupported_extension_lists_supported_types(self) -> None:
        with pytest.raises(InvalidFileError, match=r"Only \.docx, \.md and \.pdf files are accepted"):
            _extract("resume.docm", b"PK\x03\x04")

    def test_no_extension(self) -> None:
        with pytest.raises(InvalidFileError, match="'unknown'"):
            _extract("resume", b"data")
