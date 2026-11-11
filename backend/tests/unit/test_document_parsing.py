"""Document parsing: DOCX, multi-page PDF, Markdown, normalisation and sufficiency checks."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.core.errors import InvalidFileError
from app.parsing import docx as docx_module
from app.parsing.files import (
    ExtractedDocument,
    ensure_sufficient_resume_text,
    read_document,
)
from app.parsing.normalize import normalize_text, word_count
from tests.fixtures.documents import (
    SAMPLE_DOCX_BODY,
    SAMPLE_RESUME_MD,
    docx_paragraph,
    docx_table,
    make_docx,
    make_multipage_pdf,
    make_pdf,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _read(filename: str, data: bytes, content_type: str = "", **limits: int) -> ExtractedDocument:
    return read_document(
        filename=filename,
        content_type=content_type,
        stream=io.BytesIO(data),
        max_bytes=limits.get("max_bytes", 5 * 1024 * 1024),
        max_pdf_pages=limits.get("max_pdf_pages", 20),
    )


class TestNormalisation:
    @pytest.mark.parametrize("bullet", ["•", "●", "▪", "◦", "➢", "✓", "*", "+", "–", "—"])
    def test_bullet_glyphs_become_dash_items(self, bullet: str) -> None:
        assert normalize_text(f"{bullet} Built APIs") == "- Built APIs"

    def test_whitespace_ligatures_and_invisible_characters(self) -> None:
        raw = "Jane  Doe​\r\nﬁnance   team\t\tlead\r\n\n\n\n\nNext"
        assert normalize_text(raw) == "Jane Doe\nfinance team lead\n\nNext"

    def test_control_characters_removed(self) -> None:
        assert normalize_text("A\x00B\x07C") == "ABC"

    def test_lone_bullet_glyph_lines_dropped(self) -> None:
        assert normalize_text("•\nBuilt APIs") == "Built APIs"

    def test_idempotent(self) -> None:
        once = normalize_text(SAMPLE_RESUME_MD)
        assert normalize_text(once) == once

    def test_word_count(self) -> None:
        assert word_count("Built C++ and C# services, 3x faster.") == 7


class TestDocx:
    def test_extracts_headings_lists_and_skips_deleted_text(self) -> None:
        doc = _read("cv.docx", make_docx(SAMPLE_DOCX_BODY), DOCX_MIME)
        assert doc.format == "docx"
        assert "# Summary" in doc.text
        assert "## Senior Software Engineer, Acme Corp, Jan 2021 - Present" in doc.text
        assert "- Led migration of 40 services to Kubernetes, cutting deploy time by 35%." in doc.text
        assert "Old draft text" not in doc.text  # tracked deletion
        assert doc.styled_heading_count == 6
        assert doc.table_count == 0
        assert len(doc.content_sha256) == 64

    def test_tables_are_flattened_and_counted(self) -> None:
        doc = _read("cv.docx", make_docx([docx_table([["Python", "5 years"], ["Go", "1 year"]])]))
        assert doc.table_count == 1
        assert "Python | 5 years" in doc.text

    def test_page_header_text_is_included_and_flagged(self) -> None:
        doc = _read("cv.docx", make_docx([docx_paragraph("Body text here")], header=["jane@example.com"]))
        assert doc.text.startswith("jane@example.com")
        assert doc.contact_in_page_header
        assert doc.page_header_text == "jane@example.com"
        assert doc.body_text == "Body text here"

    def test_hyperlink_text_is_kept(self) -> None:
        doc = _read("cv.docx", make_docx([docx_paragraph("github.com/janedoe", link=True)]))
        assert "github.com/janedoe" in doc.text

    def test_password_protected_or_legacy_doc(self) -> None:
        ole = docx_module.OLE_MAGIC + b"\x00" * 512
        with pytest.raises(InvalidFileError, match=r"password-protected or in the old \.doc format"):
            _read("cv.docx", ole)

    def test_doc_extension_gets_conversion_hint(self) -> None:
        with pytest.raises(InvalidFileError, match=r"Save \.doc files as \.docx"):
            _read("cv.doc", docx_module.OLE_MAGIC)

    def test_corrupt_zip(self) -> None:
        with pytest.raises(InvalidFileError, match="corrupted"):
            _read("cv.docx", b"PK\x03\x04garbage-not-a-zip")

    def test_zip_without_word_document(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as package:
            package.writestr("hello.txt", "hi")
        with pytest.raises(InvalidFileError, match="valid Word"):
            _read("cv.docx", buffer.getvalue())

    def test_empty_document(self) -> None:
        with pytest.raises(InvalidFileError, match="No extractable text"):
            _read("cv.docx", make_docx([docx_paragraph("")]))

    def test_dtd_rejected(self) -> None:
        malicious = (
            b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b"<w:body><w:p><w:r><w:t>&lol2;</w:t></w:r></w:p></w:body></w:document>"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as package:
            package.writestr("word/document.xml", malicious)
        with pytest.raises(InvalidFileError, match="unsupported XML"):
            _read("cv.docx", buffer.getvalue())

    def test_zip_bomb_rejected_before_decompression(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(docx_module, "MAX_TOTAL_UNCOMPRESSED_BYTES", 1024 * 1024)
        bomb = make_docx(SAMPLE_DOCX_BODY, extra_parts={"word/media/padding.bin": b"\x00" * (2 * 1024 * 1024)})
        assert len(bomb) < 50_000  # tiny on the wire, huge when inflated
        with pytest.raises(InvalidFileError, match="too large when uncompressed"):
            _read("cv.docx", bomb)

    def test_large_document(self) -> None:
        body = [docx_paragraph(f"Delivered project number {i} on time.", numbered=True) for i in range(2000)]
        doc = _read("cv.docx", make_docx(body))
        assert doc.text.count("\n- ") == 1999

    def test_wrong_signature(self) -> None:
        with pytest.raises(InvalidFileError, match="does not look like a valid Word"):
            _read("cv.docx", b"%PDF-1.4 actually a pdf")


class TestPdf:
    def test_multipage_extraction(self) -> None:
        doc = _read("cv.pdf", make_multipage_pdf(["First page text with content", "Second page text with content"]))
        assert doc.page_count == 2
        assert "First page" in doc.text
        assert "Second page" in doc.text
        assert doc.pages_without_text == []
        assert doc.warnings == []

    def test_partially_scanned_pdf_warns(self) -> None:
        doc = _read("cv.pdf", make_multipage_pdf(["Jane Doe engineer with real text here", "", ""]))
        assert doc.pages_without_text == [2, 3]
        assert "Page(s) 2, 3" in doc.warnings[0]

    def test_twenty_page_document_accepted(self) -> None:
        doc = _read("cv.pdf", make_multipage_pdf([f"Page {i} of the document with words" for i in range(20)]))
        assert doc.page_count == 20

    @pytest.mark.parametrize(
        ("pages", "ok"),
        [
            (["Page 1"], False),  # only a page number in the text layer
            (["Jane Doe senior engineer with Python experience"], True),  # 41 letters/digits
            (["Short text here ok xx", "", "", ""], False),  # 1 text page out of 4
        ],
    )
    def test_scanned_pdf_sufficiency(self, pages: list[str], ok: bool) -> None:
        doc = _read("cv.pdf", make_multipage_pdf(pages) if len(pages) > 1 else make_pdf(pages[0]))
        if ok:
            ensure_sufficient_resume_text(doc, min_pdf_chars=40)
        else:
            with pytest.raises(InvalidFileError, match="scanned or image-only"):
                ensure_sufficient_resume_text(doc, min_pdf_chars=40)


class TestMarkdown:
    def test_markdown_normalised(self) -> None:
        doc = _read("cv.md", "# Jane\n* Built APIs\n• Shipped features".encode(), "text/markdown")
        assert doc.text == "# Jane\n- Built APIs\n- Shipped features"
        assert doc.format == "markdown"

    def test_sufficiency_check_does_not_apply_to_text_formats(self) -> None:
        doc = _read("cv.md", b"# Jane")
        ensure_sufficient_resume_text(doc, min_pdf_chars=40)
