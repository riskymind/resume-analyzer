"""Milestone 6 export quality: the five templates, coursework, page footers, DOCX structure, PDF fonts and page
breaks, and the acknowledgement required before exporting unverified claims.

DOCX checks are structural (python-docx and the raw XML); they cannot show how Word lays the page out. PDF
checks need WeasyPrint's system libraries and are skipped without them.
"""

from __future__ import annotations

import copy
import io
import re
import zipfile
from typing import Any

import pytest
from docx import Document
from docx.oxml.ns import qn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import select

from app.db.models import RewriteExport
from app.documents import render
from app.documents.templates import TEMPLATES
from app.schemas.rewrite import DocBullet, ResumeDocument
from app.services.rewriting.verification import verify_document
from tests.fixtures.export_samples import edge_case_document, graduate_document, long_document
from tests.fixtures.rewrite import sample_context, sample_document
from tests.integration.test_rewrite_exports import ALL_TEMPLATES, PDF_AVAILABLE, export, needs_pdf
from tests.integration.test_rewrites_api import REWRITES, create, patch, submit_job, upload_resume


@pytest.fixture
def rewrite(client: TestClient) -> dict[str, Any]:
    return create(client, resume_id=upload_resume(client), job_id=submit_job(client))


def _edit(client: TestClient, rewrite: dict[str, Any], change: Any) -> dict[str, Any]:
    content = copy.deepcopy(rewrite["content"])
    change(content)
    res = patch(client, rewrite, content=content)
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def _docx(document: ResumeDocument, template: str) -> Any:
    return Document(io.BytesIO(render.render_docx(document, template)))


def _paragraph_texts(document: Any) -> list[str]:
    return [p.text for p in document.paragraphs]


# --------------------------------------------------------------------------- template registry


def test_registry_has_the_five_templates() -> None:
    assert list(TEMPLATES) == ["modern", "minimal", "corporate", "technical", "graduate"]
    assert {t.name for t in TEMPLATES.values()} == {
        "Modern professional",
        "Minimalist",
        "Traditional corporate",
        "Technical",
        "Graduate",
    }
    for template in TEMPLATES.values():
        # Every template renders every section exactly once.
        assert sorted(template.sections) == sorted(
            ["summary", "experience", "projects", "skills", "education", "certifications", "languages"]
        )


def test_templates_endpoint_lists_five(client: TestClient) -> None:
    keys = [t["key"] for t in client.get(f"{REWRITES}/templates").json()]
    assert keys == ALL_TEMPLATES


# --------------------------------------------------------------------------- technical and graduate layouts


def test_technical_puts_skills_first_and_stack_before_description() -> None:
    texts = _paragraph_texts(_docx(graduate_document(), "technical"))
    headings = [t for t in texts if t in {"SKILLS", "EXPERIENCE", "PROJECTS", "EDUCATION"}]
    assert headings == ["SKILLS", "EXPERIENCE", "PROJECTS", "EDUCATION"]
    project = texts.index("Course reviews API")
    assert texts[project + 1] == "Tech stack: Python, FastAPI, Docker"
    assert texts[project + 2].startswith("REST API for anonymous course reviews")
    html = render.render_html(graduate_document(), "technical")
    assert html.index("Tech stack:") < html.index("REST API for anonymous")


def test_graduate_leads_with_education_coursework_then_projects() -> None:
    texts = _paragraph_texts(_docx(graduate_document(), "graduate"))
    headings = [t for t in texts if t in {"Education", "Projects", "Experience", "Skills", "Certifications"}]
    assert headings == ["Education", "Projects", "Experience", "Skills", "Certifications"]
    assert "Relevant coursework: Algorithms and Data Structures, Databases, Human-Computer Interaction, Networks" in (
        texts
    )
    html = render.render_html(graduate_document(), "graduate")
    assert html.index("Relevant coursework:") < html.index(">Projects<") < html.index(">Experience<")


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_coursework_is_rendered_in_every_template(template: str) -> None:
    assert "Relevant coursework:" in render.render_html(graduate_document(), template)
    assert any(t.startswith("Relevant coursework:") for t in _paragraph_texts(_docx(graduate_document(), template)))


# --------------------------------------------------------------------------- coursework verification


def test_coursework_in_the_original_resume_is_supported() -> None:
    ctx = sample_context(with_job=False)
    content = ctx.original.model_copy(deep=True)
    content.education[0].coursework = ["Computer Science"]  # stated in the sample resume
    summary = verify_document(content, ctx, [])
    assert not [i for i in summary.issues if i.code == "unsupported_coursework"]


def test_added_coursework_is_flagged_as_an_unsupported_user_claim() -> None:
    ctx = sample_context(with_job=False)
    content = ctx.original.model_copy(deep=True)
    content.education[0].coursework = ["Quantum Field Theory"]
    summary = verify_document(content, ctx, [])
    issues = [i for i in summary.issues if i.code == "unsupported_coursework"]
    assert len(issues) == 1
    assert (issues[0].severity, issues[0].origin, issues[0].term) == ("blocking", "user", "Quantum Field Theory")
    assert summary.status == "unsupported"


def test_coursework_validation() -> None:
    with pytest.raises(ValueError, match="120 characters"):
        ResumeDocument.model_validate({"education": [{"id": "e", "coursework": ["x" * 121]}]})
    doc = ResumeDocument.model_validate({"education": [{"id": "e", "coursework": ["  Databases ", " "]}]})
    assert doc.education[0].coursework == ["Databases"]
    # Versions saved before the field existed still load.
    assert ResumeDocument.model_validate({"education": [{"id": "e"}]}).education[0].coursework == []


# --------------------------------------------------------------------------- export acknowledgement


class TestAcknowledgement:
    def test_verified_content_exports_without_acknowledgement(
        self, app: FastAPI, client: TestClient, rewrite: dict[str, Any]
    ) -> None:
        assert rewrite["verification"]["status"] == "verified"
        assert export(client, rewrite, format="docx").status_code == 200
        with app.state.db.session() as db:
            row = db.scalar(select(RewriteExport))
            assert row is not None
            assert (row.verification_status, row.acknowledged_unverified) == ("verified", False)

    def test_unverified_user_claims_need_acknowledgement_and_are_not_removed(
        self, app: FastAPI, client: TestClient, rewrite: dict[str, Any]
    ) -> None:
        edited = _edit(client, rewrite, lambda c: c.update(summary="Backend engineer certified in Terraform."))
        assert edited["verification"]["status"] == "unsupported"
        assert all(i["origin"] == "user" for i in edited["verification"]["issues"] if i["severity"] == "blocking")

        refused = export(client, edited, format="docx")
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "acknowledgement_required"
        assert "could not be verified" in refused.json()["detail"]
        assert export(client, edited, format="pdf").status_code == 409  # checked before the PDF engine runs

        accepted = export(client, edited, format="docx", acknowledge_unverified=True)
        assert accepted.status_code == 200
        text = "\n".join(p.text for p in Document(io.BytesIO(accepted.content)).paragraphs)
        assert "Backend engineer certified in Terraform." in text  # the user's own wording is kept
        with app.state.db.session() as db:
            row = db.scalar(select(RewriteExport))
            assert row is not None
            assert (row.version_number, row.verification_status, row.acknowledged_unverified) == (
                2,
                "unsupported",
                True,
            )

    def test_acknowledgement_is_checked_against_the_version_exported(
        self, client: TestClient, rewrite: dict[str, Any]
    ) -> None:
        edited = _edit(client, rewrite, lambda c: c.update(summary="Backend engineer certified in Terraform."))
        # Version 1 (verified) still exports without confirmation; version 2 needs it.
        assert export(client, edited, format="docx", version=1).status_code == 200
        assert export(client, edited, format="docx", version=2).status_code == 409

    def test_detail_never_labels_user_claims_as_verified(self, client: TestClient, rewrite: dict[str, Any]) -> None:
        edited = _edit(
            client, rewrite, lambda c: c["education"][0].update(coursework=["Distributed Systems", "Computer Science"])
        )
        issues = [i for i in edited["verification"]["issues"] if i["code"] == "unsupported_coursework"]
        assert [i["term"] for i in issues] == ["Distributed Systems"]
        assert edited["verification"]["status"] == "unsupported"
        summary = next(item for item in client.get(REWRITES).json() if item["id"] == edited["id"])
        assert summary["verification_status"] == "unsupported"


# --------------------------------------------------------------------------- footers


def test_docx_footer_has_page_fields_only_after_the_first_page() -> None:
    document = _docx(sample_document(), "modern")
    section = document.sections[0]
    assert section.different_first_page_header_footer is True
    assert all(not p.text.strip() for p in section.first_page_footer.paragraphs)
    footer_xml = section.footer._element.xml
    assert 'w:instr="PAGE"' in footer_xml
    assert 'w:instr="NUMPAGES"' in footer_xml
    assert "Jane Doe" in section.footer.paragraphs[0].text
    # Contact details stay in the body, not in a header/footer an ATS may skip.
    assert "jane.doe@example.com" not in footer_xml


def test_pdf_footer_css_cannot_be_escaped_by_the_name() -> None:
    document = sample_document()
    document.contact.name = 'Eve"; } body { display:none } </style><script>x</script>'
    html = render.render_html(document, "modern")
    style = html[html.index("<style>") : html.index("</style>")]
    assert "display:none" not in style
    assert "<script" not in style
    footer = re.search(r'content: "([^"]*)\\2014', style)
    assert footer is not None
    assert footer.group(1).strip() == "Eve body displaynone stylescriptxscript"


# --------------------------------------------------------------------------- DOCX structure (all templates)


def _xml(data: bytes, part: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(part).decode()


@pytest.mark.parametrize("template", ALL_TEMPLATES)
@pytest.mark.parametrize("sample", [sample_document, graduate_document, long_document, edge_case_document])
def test_docx_structure(template: str, sample: Any) -> None:
    source = sample()
    data = render.render_docx(source, template)
    document = Document(io.BytesIO(data))
    body = _xml(data, "word/document.xml")

    # Single column, real paragraphs: no tables, text boxes, drawings or section columns.
    assert not document.tables
    for tag in ("w:tbl", "w:txbxContent", "w:drawing", "w:pict", 'w:cols w:num="2"'):
        assert f"<{tag}" not in body
    # Page setup: A4 with the template margins.
    section = document.sections[0]
    assert section.page_width is not None
    assert section.page_height is not None
    assert section.left_margin is not None
    assert (round(section.page_width.mm), round(section.page_height.mm)) == (210, 297)
    assert round(section.left_margin.mm) == 16
    # Every used style exists; bullets use Word's list style with numbering (real hanging indent).
    names = {p.style.name for p in document.paragraphs if p.style is not None}
    assert names <= {"Normal", "List Bullet"}
    bullets = [p for p in document.paragraphs if p.style is not None and p.style.name == "List Bullet"]
    expected_bullets = sum(len([b for b in e.bullets if b.text.strip()]) for e in source.experience) + len(
        source.certifications
    )
    assert len(bullets) == expected_bullets
    numbering = document.styles["List Bullet"].element.pPr.find(qn("w:numPr"))
    assert numbering is not None
    assert not any(p.text.lstrip().startswith(("•", "-", "●")) for p in bullets)  # no doubled glyphs
    # Headings stay with their content; entry heads use a right tab stop for dates.
    template_def = TEMPLATES[template]
    heading_texts = {
        (title.upper() if template_def.heading_upper else title)
        for title in ("Experience", "Education", "Skills", "Projects", "Professional Summary")
    }
    for paragraph in document.paragraphs:
        if paragraph.text in heading_texts:
            assert paragraph.paragraph_format.keep_with_next
    dated = [p for p in document.paragraphs if "\t" in p.text]
    assert dated, "entries with dates use a tab stop"
    for paragraph in dated:
        stops = paragraph.paragraph_format.tab_stops
        assert len(stops) == 1
        assert round(stops[0].position.mm) == 178
    for entry in source.experience:
        if entry.start_date:
            assert any(entry.start_date in p.text for p in dated)
    # Hyperlinks: only http(s)/mailto, each with a relationship, and the visible text is present.
    targets = {rel.rId: rel.target_ref for rel in document.part.rels.values() if rel.is_external}
    assert targets
    assert all(re.match(r"^(https?://|mailto:)", url) for url in targets.values())
    for rel_id in re.findall(r'<w:hyperlink [^>]*r:id="([^"]+)"', body):
        assert rel_id in targets
    if source.contact.email:
        assert f"mailto:{source.contact.email}" in targets.values()
    # No control characters or replacement glyphs anywhere in the text.
    text = "\n".join(p.text for p in document.paragraphs)
    assert "�" not in text
    assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text)


def test_docx_wraps_long_content_without_losing_text() -> None:
    document = edge_case_document()
    texts = _paragraph_texts(_docx(document, "minimal"))
    assert any("a1b2c3d4e5" * 14 in t for t in texts)
    assert any(t == "Zoë Ñúñez-O'Brien" for t in texts)
    assert any("€2,000" in t and "日本語" in t for t in texts)


# --------------------------------------------------------------------------- PDF (needs Pango)


def _pdf(document: ResumeDocument, template: str) -> PdfReader:
    return PdfReader(io.BytesIO(render.render_pdf(document, template)))


def _fonts(reader: PdfReader) -> dict[str, bool]:
    """Font name -> embedded (has a font file)."""

    fonts: dict[str, bool] = {}
    for page in reader.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        for ref in (resources.get_object().get("/Font") or {}).values():
            font = ref.get_object()
            descriptors = [font.get("/FontDescriptor")] + [
                d.get_object().get("/FontDescriptor") for d in font.get("/DescendantFonts", [])
            ]
            embedded = any(
                d is not None and any(k in d.get_object() for k in ("/FontFile", "/FontFile2", "/FontFile3"))
                for d in descriptors
            )
            fonts[str(font.get("/BaseFont"))] = embedded
    return fonts


@needs_pdf
@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_pdf_fonts_are_embedded_and_text_is_clean(template: str) -> None:
    reader = _pdf(graduate_document(), template)
    fonts = _fonts(reader)
    assert fonts
    assert all(fonts.values()), fonts
    text = " ".join(page.extract_text() or "" for page in reader.pages)
    assert "�" not in text
    assert "Relevant coursework" in text
    uris = {
        annotation.get_object()["/A"]["/URI"]
        for page in reader.pages
        for annotation in page.get("/Annots", [])
        if "/A" in annotation.get_object()
    }
    assert {"mailto:alex.rivera@example.com", "https://github.com/alex-rivera-example"} <= uris


@needs_pdf
@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_pdf_long_resume_pages_and_footer(template: str) -> None:
    document = long_document()
    reader = _pdf(document, template)
    pages = len(reader.pages)
    assert pages >= 3
    texts = [re.sub(r"\s+", " ", page.extract_text() or "") for page in reader.pages]
    assert "page 1 of" not in texts[0]  # no footer on the first page
    for number in range(2, pages + 1):
        assert f"page {number} of {pages}" in texts[number - 1]
    joined = " ".join(texts)
    for role in document.experience:
        for bullet in role.bullets:
            entry = re.search(r"\(entry [0-9.]+\)", bullet.text)
            assert entry is not None
            assert entry.group(0) in joined, f"{entry.group(0)} missing ({template})"


@needs_pdf
def test_pdf_long_unbroken_text_wraps_instead_of_overflowing() -> None:
    """A 140-character token without spaces is broken across lines (overflow-wrap), so nothing runs off the page."""

    token = "a1b2c3d4e5" * 14
    # Not edge_case_document(): its CJK glyphs come from a fallback font that pypdf cannot map back to text
    # in the Linux image (pdftotext reads it correctly), which would make this check fail for the wrong reason.
    document = sample_document()
    document.experience[0].bullets.append(DocBullet(id="long-token", text=f"Unbroken token: {token} ends here."))
    for template in ALL_TEMPLATES:
        text = _pdf(document, template).pages[0].extract_text() or ""
        assert token not in text, f"{template}: token on a single line"
        assert token in re.sub(r"\s+", "", text), f"{template}: token text lost"


def test_pdf_availability_flag_matches_environment() -> None:
    """Documents which PDF tests ran: PDF_AVAILABLE is False on a host without Pango (those tests skip)."""

    assert isinstance(PDF_AVAILABLE, bool)


# --------------------------------------------------------------------------- previews


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_preview_for_every_template(client: TestClient, rewrite: dict[str, Any], template: str) -> None:
    res = client.get(f"{REWRITES}/{rewrite['id']}/preview", params={"template": template})
    assert res.status_code == 200
    html = res.json()["html"]
    assert TEMPLATES[template].css_font_stack in html
    assert "Jane Doe" in html
