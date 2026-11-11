"""DOCX resumes with python-docx, following the same template definition as the HTML/PDF output.

ATS considerations: a single column, real paragraphs (no tables or text
boxes), contact details in the document body rather than the page header,
Word's built-in "List Bullet" style for bullets, and clickable hyperlinks.
Continuation pages get a small footer with the candidate's name and page
number (Word fields); the first page has none.
"""

from __future__ import annotations

import re

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from docx.text.paragraph import Paragraph

from app.documents.templates import SECTION_TITLES, Template
from app.schemas.rewrite import ResumeDocument
from app.services.rewriting.document import certification_line, date_range

_MARGIN_LR = Mm(16)
_MARGIN_TB = Mm(15)
_CONTENT_WIDTH = Mm(210 - 32)
_SAFE_LINK = re.compile(r"^(https?://|mailto:)[^\s<>\"']+$", re.IGNORECASE)


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color.upper())


def _hyperlink(paragraph: Paragraph, text: str, url: str, *, color: str | None = None) -> None:
    if not _SAFE_LINK.match(url):
        paragraph.add_run(text)
        return
    part = paragraph.part
    rel_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rel_id)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    if color:
        colour = OxmlElement("w:color")
        colour.set(qn("w:val"), color)
        props.append(colour)
    run.append(props)
    text_element = OxmlElement("w:t")
    text_element.text = text
    text_element.set(qn("xml:space"), "preserve")
    run.append(text_element)
    link.append(run)
    paragraph._p.append(link)


def _field(paragraph: Paragraph, instruction: str, *, half_points: int) -> None:
    """A simple Word field such as PAGE or NUMPAGES (Word updates it when the document is opened or printed)."""

    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), instruction)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), str(half_points))
    props.append(size)
    run.append(props)
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


def _bottom_rule(paragraph: Paragraph, color: str) -> None:
    props = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    props.append(borders)


class _Builder:
    def __init__(self, template: Template) -> None:
        self.t = template
        self.doc: DocxDocument = Document()
        section = self.doc.sections[0]
        section.page_width, section.page_height = Mm(210), Mm(297)
        section.left_margin = section.right_margin = _MARGIN_LR
        section.top_margin = section.bottom_margin = _MARGIN_TB
        normal = self.doc.styles["Normal"]
        normal.font.name = template.docx_font
        normal.font.size = Pt(template.body_pt)
        normal.font.color.rgb = RGBColor(0x1D, 0x1F, 0x21)
        r_fonts = normal.element.rPr.rFonts
        for attribute in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            r_fonts.set(qn(attribute), template.docx_font)
        normal.paragraph_format.space_after = Pt(2)
        normal.paragraph_format.line_spacing = round(
            template.line_height * 0.84, 2
        )  # CSS line-height vs Word "multiple"
        bullets = self.doc.styles["List Bullet"]
        bullets.font.name = template.docx_font
        bullets.font.size = Pt(template.body_pt)
        bullets.paragraph_format.space_after = Pt(1.5)

    def footer(self, name: str | None) -> None:
        section = self.doc.sections[0]
        section.different_first_page_header_footer = True
        section.footer_distance = Mm(8)
        paragraph = section.footer.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph.add_run(f"{name or 'Resume'} \u2014 page ").font.size = Pt(8)
        _field(paragraph, "PAGE", half_points=16)
        paragraph.add_run(" of ").font.size = Pt(8)
        _field(paragraph, "NUMPAGES", half_points=16)

    def paragraph(self, *, keep_with_next: bool = False, space_after: float | None = None) -> Paragraph:
        paragraph = self.doc.add_paragraph()
        paragraph.paragraph_format.keep_with_next = keep_with_next
        if space_after is not None:
            paragraph.paragraph_format.space_after = Pt(space_after)
        return paragraph

    def heading(self, title: str) -> None:
        paragraph = self.paragraph(keep_with_next=True, space_after=3)
        paragraph.paragraph_format.space_before = Pt(8)
        run = paragraph.add_run(title.upper() if self.t.heading_upper else title)
        run.bold = True
        run.font.size = Pt(self.t.heading_pt)
        run.font.color.rgb = _rgb(self.t.accent)
        if self.t.heading_rule:
            _bottom_rule(paragraph, self.t.accent)

    def entry_head(self, title: str | None, subtitle: str | None, dates: str | None) -> None:
        paragraph = self.paragraph(keep_with_next=True, space_after=1)
        paragraph.paragraph_format.tab_stops.add_tab_stop(_CONTENT_WIDTH, WD_TAB_ALIGNMENT.RIGHT)
        if title:
            paragraph.add_run(title).bold = True
        if subtitle:
            paragraph.add_run((", " if title else "") + subtitle)
        if dates:
            paragraph.add_run("\t" + dates)

    def bullet(self, text: str) -> None:
        paragraph = self.doc.add_paragraph(text, style="List Bullet")
        paragraph.paragraph_format.keep_together = True

    def build(self, document: ResumeDocument) -> DocxDocument:
        contact = document.contact
        if contact.name:
            paragraph = self.paragraph(space_after=2)
            run = paragraph.add_run(contact.name)
            run.bold = True
            run.font.size = Pt(self.t.name_pt)
            run.font.color.rgb = _rgb(self.t.accent)
            if self.t.centered_header:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        parts: list[tuple[str, str | None]] = []
        if contact.email:
            parts.append((contact.email, f"mailto:{contact.email}"))
        if contact.phone:
            parts.append((contact.phone, None))
        if contact.location:
            parts.append((contact.location, None))
        for link in contact.links:
            parts.append((re.sub(r"^https?://(www\.)?", "", link.url).rstrip("/"), link.url))
        if parts:
            paragraph = self.paragraph(space_after=6)
            if self.t.centered_header:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for index, (text, url) in enumerate(parts):
                if index:
                    paragraph.add_run(" | ")
                if url:
                    _hyperlink(paragraph, text, url)
                else:
                    paragraph.add_run(text)

        for section in self.t.sections:
            getattr(self, f"_{section}")(document)
        self.footer(contact.name)
        return self.doc

    # ----------------------------------------------------------------- sections

    def _summary(self, document: ResumeDocument) -> None:
        if document.summary:
            self.heading(SECTION_TITLES["summary"])
            self.paragraph().add_run(document.summary)

    def _experience(self, document: ResumeDocument) -> None:
        if not document.experience:
            return
        self.heading(SECTION_TITLES["experience"])
        for entry in document.experience:
            subtitle = " · ".join(part for part in (entry.employer, entry.location) if part) or None
            self.entry_head(entry.title, subtitle, date_range(entry.start_date, entry.end_date))
            for bullet in entry.bullets:
                if bullet.text.strip():
                    self.bullet(bullet.text)

    def _projects(self, document: ResumeDocument) -> None:
        if not document.projects:
            return
        self.heading(SECTION_TITLES["projects"])
        for project in document.projects:
            self.entry_head(project.name or "Project", None, None)
            if self.t.stack_first:
                self._technologies(project.technologies)
            if project.description:
                self.paragraph().add_run(project.description)
            if not self.t.stack_first:
                self._technologies(project.technologies)

    def _technologies(self, technologies: list[str]) -> None:
        if technologies:
            paragraph = self.paragraph()
            paragraph.add_run(f"{self.t.tech_label}: ").bold = True
            paragraph.add_run(", ".join(technologies))

    def _skills(self, document: ResumeDocument) -> None:
        if not (document.technical_skills or document.soft_skills):
            return
        self.heading(SECTION_TITLES["skills"])
        for label, values in (("Technical", document.technical_skills), ("Professional", document.soft_skills)):
            if values:
                paragraph = self.paragraph()
                paragraph.add_run(f"{label}: ").bold = True
                paragraph.add_run(", ".join(values))

    def _education(self, document: ResumeDocument) -> None:
        if not document.education:
            return
        self.heading(SECTION_TITLES["education"])
        for edu in document.education:
            degree = " ".join(part for part in (edu.qualification, edu.field_of_study) if part) or None
            self.entry_head(degree, edu.institution, date_range(edu.start_date, edu.end_date))
            if edu.grade:
                self.paragraph().add_run(edu.grade)
            if edu.coursework:
                paragraph = self.paragraph()
                paragraph.add_run("Relevant coursework: ").bold = True
                paragraph.add_run(", ".join(edu.coursework))

    def _certifications(self, document: ResumeDocument) -> None:
        if not document.certifications:
            return
        self.heading(SECTION_TITLES["certifications"])
        for cert in document.certifications:
            self.bullet(certification_line(cert))

    def _languages(self, document: ResumeDocument) -> None:
        if not document.languages:
            return
        self.heading(SECTION_TITLES["languages"])
        self.paragraph().add_run(
            ", ".join(
                f"{lang.name} ({lang.proficiency})" if lang.proficiency else lang.name for lang in document.languages
            )
        )


def build_docx(document: ResumeDocument, template: Template) -> DocxDocument:
    return _Builder(template).build(document)
