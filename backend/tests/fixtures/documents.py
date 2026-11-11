"""Builders for test documents, generated in-process so no binary fixtures live in git."""

from __future__ import annotations


def _pdf_escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(text: str) -> bytes:
    """Return a minimal, valid single-page PDF whose text layer contains ``text``."""

    lines = text.split("\n") if text else []
    content = "BT /F1 11 Tf 72 720 Td 14 TL " + " ".join(f"({_pdf_escape(line)}) Tj T*" for line in lines) + " ET"
    # Base-14 fonts use Latin-1; map typographic dashes to "-" and replace anything else unsupported.
    stream = content.replace("\u2014", "-").replace("\u2013", "-").encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_offset = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_offset)
    return bytes(out)


def make_blank_pdf() -> bytes:
    """A valid PDF with no text layer (simulates an image-only scan)."""

    return make_pdf("")


SAMPLE_RESUME_MD = """# Jane Doe
jane.doe@example.com | +1 555 010 0199 | https://janedoe.dev

## Summary
Backend engineer with 6 years of experience building Python APIs.

## Experience
### Senior Software Engineer — Acme Corp (2021 – Present)
- Led migration of 40 services to Kubernetes, cutting deploy time by 35%.
- Built FastAPI services handling 2M requests per day.

### Software Engineer — Initech (2018 – 2021)
- Maintained PostgreSQL data pipelines.

## Education
BSc Computer Science, State University, 2018

## Skills
Python, FastAPI, PostgreSQL, Docker, Kubernetes, AWS
"""

SAMPLE_JD = """Senior Backend Engineer at Globex
Requirements: 5+ years Python, FastAPI or Django, PostgreSQL, Docker, Kubernetes.
Nice to have: Terraform, GCP. Bachelor's degree in Computer Science or related field.
"""


# A model response for SAMPLE_RESUME_MD, used by the fake AI provider. For any
# other uploaded resume the application's verification step discards whatever
# is not present in that resume, exactly as it would with a real model.
SAMPLE_EXTRACTION: dict[str, object] = {
    "name": {"value": "Jane Doe"},
    "location": {"value": None},
    "summary": {"value": "Backend engineer with 6 years of experience building Python APIs."},
    "experience": [
        {
            "title": {"value": "Senior Software Engineer"},
            "employer": {"value": "Acme Corp"},
            "start_date": {"value": "2021"},
            "end_date": {"value": "Present"},
            "bullets": [
                {
                    "text": "Led migration of 40 services to Kubernetes, cutting deploy time by 35%.",
                    "type": "achievement",
                },
                {"text": "Built FastAPI services handling 2M requests per day.", "type": "achievement"},
            ],
        },
        {
            "title": {"value": "Software Engineer"},
            "employer": {"value": "Initech"},
            "start_date": {"value": "2018"},
            "end_date": {"value": "2021"},
            "bullets": [{"text": "Maintained PostgreSQL data pipelines.", "type": "responsibility"}],
        },
    ],
    "education": [
        {
            "institution": {"value": "State University"},
            "qualification": {"value": "BSc"},
            "field_of_study": {"value": "Computer Science"},
            "end_date": {"value": "2018"},
        }
    ],
    "technical_skills": [{"name": name} for name in ("Python", "FastAPI", "PostgreSQL", "Docker", "Kubernetes", "AWS")],
    "soft_skills": [{"name": "Leadership", "evidence": "Led migration of 40 services to Kubernetes"}],
    "certifications": [],
    "projects": [],
    "languages": [],
}


# A model response for SAMPLE_JD. The application verifies every item against
# the submitted job description, so for other job descriptions anything not
# present in that text is discarded, exactly as with a real model.
SAMPLE_JOB_EXTRACTION: dict[str, object] = {
    "title": {"value": "Senior Backend Engineer"},
    "company": {"value": "Globex"},
    "seniority": {"value": "Senior"},
    "requirements": [
        {
            "name": "5+ years Python",
            "category": "experience",
            "classification": "required",
            "importance": "high",
            "evidence": "5+ years Python",
            "min_years": 5,
        },
        *[
            {
                "name": name,
                "category": "technical_skill",
                "classification": "required",
                "importance": "high" if name == "Python" else "medium",
                "evidence": "Requirements: 5+ years Python, FastAPI or Django, PostgreSQL, Docker, Kubernetes.",
            }
            for name in ("Python", "FastAPI", "Django", "PostgreSQL", "Docker", "Kubernetes")
        ],
        *[
            {
                "name": name,
                "category": "technical_skill",
                # Deliberately wrong: the text says "Nice to have", so code must re-classify these.
                "classification": "required",
                "importance": "low",
                "evidence": "Nice to have: Terraform, GCP.",
            }
            for name in ("Terraform", "GCP")
        ],
        {
            "name": "Bachelor's degree in Computer Science or related field",
            "category": "education",
            "classification": "required",
            "importance": "medium",
            "evidence": "Bachelor's degree in Computer Science or related field.",
        },
    ],
    "keywords": [{"term": term} for term in ("Backend", "Python", "Kubernetes", "Terraform")],
}


# --------------------------------------------------------------------------- DOCX builder

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def docx_paragraph(
    text: str, *, style: str | None = None, numbered: bool = False, deleted: str = "", link: bool = False
) -> str:
    props = ""
    if style or numbered:
        props = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "")
        props += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>' if numbered else ""
        props += "</w:pPr>"
    run = f'<w:r><w:t xml:space="preserve">{_xml_escape(text)}</w:t></w:r>'
    if link:
        run = f'<w:hyperlink r:id="rId9">{run}</w:hyperlink>'
    removed = f"<w:del><w:r><w:delText>{_xml_escape(deleted)}</w:delText></w:r></w:del>" if deleted else ""
    return f"<w:p>{props}{removed}{run}</w:p>"


def docx_table(rows: list[list[str]]) -> str:
    cells = "".join(
        "<w:tr>" + "".join(f"<w:tc>{docx_paragraph(cell)}</w:tc>" for cell in row) + "</w:tr>" for row in rows
    )
    return f"<w:tbl>{cells}</w:tbl>"


def make_docx(
    body: list[str], *, header: list[str] | None = None, extra_parts: dict[str, bytes] | None = None
) -> bytes:
    """Build a minimal valid .docx from paragraph/table XML snippets."""

    import io
    import zipfile

    def part(inner: str, root: str = "document") -> str:
        wrapper = f"<w:body>{inner}</w:body>" if root == "document" else inner
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:{root} xmlns:w="{_W_NS}" xmlns:r="{_R_NS}">{wrapper}</w:{root}>'
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        package.writestr("word/document.xml", part("".join(body)))
        if header:
            package.writestr("word/header1.xml", part("".join(docx_paragraph(line) for line in header), root="hdr"))
        for name, data in (extra_parts or {}).items():
            package.writestr(name, data)
    return buffer.getvalue()


def make_multipage_pdf(pages: list[str]) -> bytes:
    """A PDF with one page per entry; an empty string produces a page with no text layer."""

    import io

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for text in pages:
        source = make_pdf(text) if text else make_blank_pdf()
        writer.add_page(PdfReader(io.BytesIO(source)).pages[0])
    out = io.BytesIO()
    writer.write(out)
    data: bytes = out.getvalue()
    return data


SAMPLE_DOCX_BODY = [
    docx_paragraph("Jane Doe", style="Title"),
    docx_paragraph("jane.doe@example.com | +1 555 010 0199 | linkedin.com/in/janedoe"),
    docx_paragraph("Summary", style="Heading1"),
    docx_paragraph("Backend engineer with 6 years of experience building Python APIs."),
    docx_paragraph("Work Experience", style="Heading1"),
    docx_paragraph("Senior Software Engineer, Acme Corp, Jan 2021 - Present", style="Heading2"),
    docx_paragraph("Led migration of 40 services to Kubernetes, cutting deploy time by 35%.", numbered=True),
    docx_paragraph("Built FastAPI services handling 2M requests per day.", numbered=True, deleted="Old draft text"),
    docx_paragraph("Education", style="Heading1"),
    docx_paragraph("BSc Computer Science, State University, 2018"),
    docx_paragraph("Skills", style="Heading1"),
    docx_paragraph("Python, FastAPI, PostgreSQL, Docker, Kubernetes, AWS"),
]


# --------------------------------------------------------------------------- resume rewriting

# A well-behaved model response for rewriting SAMPLE_RESUME_MD against SAMPLE_JD. Item ids follow the
# document built from SAMPLE_EXTRACTION: exp-1 (Acme Corp: b1 migration, b2 FastAPI), exp-2 (Initech: b1).
SAMPLE_REWRITE: dict[str, object] = {
    "summary": {
        "text": (
            "Backend engineer with 6 years of experience building Python APIs with FastAPI and PostgreSQL, "
            "and running containerised services on Kubernetes."
        ),
        "keywords": ["Python", "FastAPI", "PostgreSQL", "Kubernetes", "Terraform"],
        "requirement_ids": [],
        "rationale": "Leads with the stack the job requires.",
    },
    "experience": [
        {
            "id": "exp-1",
            "bullets": [
                {
                    "text": "Led the migration of 40 services to Kubernetes, reducing deploy time by 35%.",
                    "source_ids": ["exp-1-b1"],
                    "keywords": ["Kubernetes"],
                    "rationale": "Clearer outcome.",
                },
                {
                    "text": "Built FastAPI services that handle 2M requests per day.",
                    "source_ids": ["exp-1-b2"],
                    "keywords": ["FastAPI"],
                    "metric_prompt": "What latency or uptime did these services achieve?",
                },
            ],
        },
        {"id": "exp-2", "bullets": [{"text": "Maintained PostgreSQL data pipelines.", "source_ids": ["exp-2-b1"]}]},
    ],
    "skills": {
        "technical": ["Python", "FastAPI", "PostgreSQL", "Kubernetes", "Docker", "AWS"],
        "soft": ["Leadership"],
        "rationale": "Required skills first.",
    },
    "alignment_notes": ["Puts the Python, FastAPI and PostgreSQL experience the job requires first."],
}
