"""Export template registry: one definition drives the HTML/PDF template and the DOCX builder.

Fonts are chosen so the PDF (rendered on Linux) and the DOCX (opened in Word)
look alike: Carlito is metric-compatible with Calibri, Caladea with Cambria,
Liberation Sans with Arial, and Liberation Serif with Times New Roman.

Every template is single column with standard section headings, real text
and no tables, images or text boxes, so all five stay ATS-readable. They
differ in typography, density and, above all, section order: what a reader
sees first.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.rewrite import TemplateInfo, TemplateKey

SectionName = str


@dataclass(frozen=True)
class Template:
    key: TemplateKey
    name: str
    description: str
    docx_font: str
    css_font_stack: str
    accent: str  # hex without '#'
    heading_upper: bool
    heading_rule: bool
    centered_header: bool
    body_pt: float
    name_pt: float
    heading_pt: float
    sections: tuple[SectionName, ...]
    tech_label: str = "Technologies"  # label of a project's technology line
    stack_first: bool = False  # show a project's technologies before its description
    line_height: float = 1.32


_CONTEMPORARY = ("summary", "experience", "projects", "skills", "education", "certifications", "languages")
_TRADITIONAL = ("summary", "experience", "education", "certifications", "skills", "projects", "languages")
# Skills and projects lead: the reader sees the stack before the job history.
_TECHNICAL = ("summary", "skills", "experience", "projects", "certifications", "education", "languages")
# Limited professional experience: education (with coursework), then projects, then experience and internships.
_GRADUATE = ("summary", "education", "projects", "experience", "skills", "certifications", "languages")

TEMPLATES: dict[str, Template] = {
    "modern": Template(
        key="modern",
        name="Modern professional",
        description="Clean sans-serif layout with a restrained accent colour. Single column, ATS-friendly.",
        docx_font="Calibri",
        css_font_stack="Calibri, Carlito, 'Liberation Sans', 'DejaVu Sans', Arial, sans-serif",
        accent="2E6F5E",
        heading_upper=True,
        heading_rule=True,
        centered_header=False,
        body_pt=10.5,
        name_pt=20,
        heading_pt=11,
        sections=_CONTEMPORARY,
    ),
    "minimal": Template(
        key="minimal",
        name="Minimalist",
        description="Black and white, no rules or colour. Plain headings for maximum ATS compatibility.",
        docx_font="Arial",
        css_font_stack="Arial, 'Liberation Sans', Helvetica, 'DejaVu Sans', sans-serif",
        accent="000000",
        heading_upper=False,
        heading_rule=False,
        centered_header=False,
        body_pt=10,
        name_pt=17,
        heading_pt=11.5,
        sections=_CONTEMPORARY,
    ),
    "corporate": Template(
        key="corporate",
        name="Traditional corporate",
        description="Serif typography, centred header and classic section order (education before skills).",
        docx_font="Times New Roman",
        css_font_stack="'Times New Roman', 'Liberation Serif', 'DejaVu Serif', Times, serif",
        accent="1F3A5F",
        heading_upper=True,
        heading_rule=True,
        centered_header=True,
        body_pt=11,
        name_pt=19,
        heading_pt=11.5,
        sections=_TRADITIONAL,
    ),
    "technical": Template(
        key="technical",
        name="Technical",
        description="Compact layout for engineering roles: skills first, then experience and projects with their "
        "technology stack.",
        docx_font="Arial",
        css_font_stack="Arial, 'Liberation Sans', Helvetica, 'DejaVu Sans', sans-serif",
        accent="1F4E79",
        heading_upper=True,
        heading_rule=True,
        centered_header=False,
        body_pt=10,
        name_pt=18,
        heading_pt=10.5,
        sections=_TECHNICAL,
        tech_label="Tech stack",
        stack_first=True,
        line_height=1.28,
    ),
    "graduate": Template(
        key="graduate",
        name="Graduate",
        description="For early-career candidates: education and relevant coursework first, then projects, "
        "internships and other experience.",
        docx_font="Cambria",
        css_font_stack="Cambria, Caladea, 'Liberation Serif', 'DejaVu Serif', Georgia, serif",
        accent="5B3A7A",
        heading_upper=False,
        heading_rule=True,
        centered_header=True,
        body_pt=10.5,
        name_pt=19,
        heading_pt=12,
        sections=_GRADUATE,
    ),
}

SECTION_TITLES = {
    "summary": "Professional Summary",
    "experience": "Experience",
    "projects": "Projects",
    "skills": "Skills",
    "education": "Education",
    "certifications": "Certifications",
    "languages": "Languages",
}


def get_template(key: str) -> Template:
    return TEMPLATES[key]


def template_infos() -> list[TemplateInfo]:
    return [TemplateInfo(key=t.key, name=t.name, description=t.description) for t in TEMPLATES.values()]
