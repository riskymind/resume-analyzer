"""Deterministic section detection on normalised resume text.

A line starts a new section when it is a short heading whose text matches a
known alias (``Work Experience``, ``EDUCATION:``, ``## Skills`` ...). Unknown
markdown/DOCX-styled headings (``## Volunteering stuff``) start an ``other``
section. Unknown ALL-CAPS lines do *not*, because job titles and employer
names are often written in capitals inside the experience section.

Everything before the first section is the ``header`` (name and contact
details on almost every resume).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

SectionKind = Literal[
    "summary",
    "experience",
    "education",
    "skills",
    "projects",
    "certifications",
    "languages",
    "achievements",
    "publications",
    "volunteering",
    "interests",
    "references",
    "contact",
    "other",
]

_ALIASES: dict[SectionKind, tuple[str, ...]] = {
    "summary": (
        "summary",
        "professional summary",
        "career summary",
        "executive summary",
        "profile",
        "professional profile",
        "personal profile",
        "about",
        "about me",
        "objective",
        "career objective",
        "personal statement",
        "overview",
        "introduction",
    ),
    "experience": (
        "experience",
        "work experience",
        "professional experience",
        "relevant experience",
        "employment",
        "employment history",
        "work history",
        "career history",
        "professional background",
        "career",
        "experience and employment",
        "industry experience",
    ),
    "education": (
        "education",
        "academic background",
        "academic history",
        "education and training",
        "academic qualifications",
        "qualifications",
        "educational background",
        "education and qualifications",
    ),
    "skills": (
        "skills",
        "technical skills",
        "core skills",
        "key skills",
        "core competencies",
        "competencies",
        "technologies",
        "tech stack",
        "tools",
        "tools and technologies",
        "skills and tools",
        "areas of expertise",
        "expertise",
        "skills and abilities",
        "technical proficiencies",
        "skills summary",
        "skill set",
        "skillset",
    ),
    "projects": (
        "projects",
        "personal projects",
        "selected projects",
        "key projects",
        "side projects",
        "academic projects",
        "open source",
        "portfolio",
    ),
    "certifications": (
        "certifications",
        "certificates",
        "certification",
        "licenses",
        "licences",
        "licenses and certifications",
        "certifications and licenses",
        "professional certifications",
        "courses",
        "training",
        "professional development",
        "courses and certifications",
    ),
    "languages": ("languages", "language skills", "spoken languages", "language proficiency"),
    "achievements": (
        "achievements",
        "awards",
        "honors",
        "honours",
        "accomplishments",
        "awards and honors",
        "awards and honours",
        "key achievements",
        "honors and awards",
    ),
    "publications": ("publications", "papers", "research", "talks", "publications and talks"),
    "volunteering": (
        "volunteering",
        "volunteer experience",
        "volunteer work",
        "community involvement",
        "leadership and volunteering",
        "extracurricular activities",
        "activities",
    ),
    "interests": ("interests", "hobbies", "hobbies and interests"),
    "references": ("references", "referees"),
    "contact": ("contact", "contact information", "contact details", "personal details", "personal information"),
}

_ALIAS_TO_KIND: dict[str, SectionKind] = {alias: kind for kind, aliases in _ALIASES.items() for alias in aliases}

_ENTRY_SECTIONS = frozenset({"experience", "education", "projects", "volunteering", "certifications"})
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_DECORATION = re.compile(r"^[\s*_=~|:-]+|[\s*_=~|:-]+$")


@dataclass
class Section:
    kind: SectionKind
    heading: str
    start_line: int  # index of the heading line
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


@dataclass
class DocumentLayout:
    header_lines: list[str]
    sections: list[Section]

    def of_kind(self, kind: SectionKind) -> list[Section]:
        return [section for section in self.sections if section.kind == kind]

    def has(self, kind: SectionKind) -> bool:
        return any(section.kind == kind and section.text for section in self.sections)

    def text_of(self, kind: SectionKind) -> str:
        return "\n".join(section.text for section in self.of_kind(kind)).strip()

    @property
    def header_text(self) -> str:
        return "\n".join(self.header_lines).strip()


def _canonical(heading: str) -> str:
    cleaned = _DECORATION.sub("", heading).lower().replace("&", " and ")
    cleaned = re.sub(r"[^a-z ]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def classify_heading(line: str) -> tuple[SectionKind, str] | None:
    """Return ``(kind, heading_text)`` if ``line`` is a section heading."""

    stripped = line.strip()
    if not stripped or stripped.startswith("- "):
        return None

    markdown = _MARKDOWN_HEADING.match(stripped)
    text = markdown.group(2).strip() if markdown else stripped
    text = _DECORATION.sub("", text)
    if not text or len(text) > 60 or len(text.split()) > 6:
        return None
    if text.endswith(".") or "@" in text:
        return None

    kind = _ALIAS_TO_KIND.get(_canonical(text))
    if kind is not None:
        return kind, text
    # Unknown headings count only when explicitly marked up as a level-2 heading
    # (markdown "##" or DOCX "Heading 2"). Level 1 is usually the person's name;
    # level 3+ is usually a job or degree entry.
    if markdown and len(markdown.group(1)) == 2:
        return "other", text
    return None


def detect_sections(text: str) -> DocumentLayout:
    header: list[str] = []
    sections: list[Section] = []
    for index, line in enumerate(text.split("\n")):
        heading = classify_heading(line)
        if heading is not None and heading[0] == "other" and sections and sections[-1].kind in _ENTRY_SECTIONS:
            heading = None  # a sub-heading for an entry (job, degree, project), not a new section
        if heading is not None:
            kind, heading_text = heading
            sections.append(Section(kind=kind, heading=heading_text, start_line=index))
        elif sections:
            sections[-1].lines.append(line)
        else:
            header.append(line)
    return DocumentLayout(header_lines=header, sections=sections)
