"""The editable resume document: built from the verified extraction, rendered to text, converted back for scoring.

Everything here is deterministic. The original document is derived only from
the verified ``StructuredResume`` (Milestone 3), so it never contains anything
the extraction step could not find in the uploaded resume.
"""

from __future__ import annotations

from app.parsing.normalize import normalize_text
from app.parsing.signals import find_metrics, is_present
from app.schemas.resume import (
    Bullet,
    Certification,
    Contact,
    EducationEntry,
    ExperienceEntry,
    ExtractionInfo,
    Language,
    Link,
    Project,
    Skill,
    StructuredResume,
    TextField,
)
from app.schemas.rewrite import (
    DocBullet,
    DocCertification,
    DocContact,
    DocEducation,
    DocExperience,
    DocLanguage,
    DocLink,
    DocProject,
    ResumeDocument,
)
from app.services.extraction import match_key


def _value(field: TextField) -> str | None:
    return field.value if field.present else None


def _ordered_bullets(entry: ExperienceEntry, text_key: str) -> list[Bullet]:
    """Bullets in the order they appear in the resume (extraction stores achievements and duties separately)."""

    def position(bullet: Bullet) -> int:
        found = text_key.find(match_key(bullet.text))
        return found if found >= 0 else len(text_key)

    return sorted(entry.bullets, key=position)


def build_document(structured: StructuredResume, text: str) -> ResumeDocument:
    """The original resume as an editable document with stable ids."""

    text_key = match_key(text)
    contact = structured.contact
    links = []
    for link in contact.links:
        try:
            links.append(DocLink(kind=link.kind, url=link.url))
        except ValueError:
            continue  # not an http(s) URL; it stays in the uploaded resume but is not made clickable
    document = ResumeDocument(
        contact=DocContact(
            name=_value(contact.name),
            email=_value(contact.email),
            phone=_value(contact.phone),
            location=_value(contact.location),
            links=links,
        ),
        summary=_value(structured.summary),
        experience=[
            DocExperience(
                id=f"exp-{index}",
                title=_value(entry.title),
                employer=_value(entry.employer),
                location=_value(entry.location),
                start_date=_value(entry.start_date),
                end_date=_value(entry.end_date),
                bullets=[
                    DocBullet(id=f"exp-{index}-b{position}", text=bullet.text, source_ids=[f"exp-{index}-b{position}"])
                    for position, bullet in enumerate(_ordered_bullets(entry, text_key), start=1)
                ],
            )
            for index, entry in enumerate(structured.experience, start=1)
        ],
        education=[
            DocEducation(
                id=f"edu-{index}",
                institution=_value(entry.institution),
                qualification=_value(entry.qualification),
                field_of_study=_value(entry.field_of_study),
                start_date=_value(entry.start_date),
                end_date=_value(entry.end_date),
                grade=_value(entry.grade),
            )
            for index, entry in enumerate(structured.education, start=1)
        ],
        certifications=[
            DocCertification(id=f"cert-{index}", name=_value(c.name), issuer=_value(c.issuer), date=_value(c.date))
            for index, c in enumerate(structured.certifications, start=1)
        ],
        projects=[
            DocProject(
                id=f"proj-{index}",
                name=_value(p.name),
                description=_value(p.description),
                technologies=list(p.technologies),
            )
            for index, p in enumerate(structured.projects, start=1)
        ],
        technical_skills=[s.name for s in structured.technical_skills],
        soft_skills=[s.name for s in structured.soft_skills],
        languages=[DocLanguage(name=lang.name, proficiency=_value(lang.proficiency)) for lang in structured.languages],
    )
    return document


# --------------------------------------------------------------------------- rendering


def date_range(start: str | None, end: str | None) -> str | None:
    if start and end:
        return f"{start} \u2013 {end}"
    return start or end


def contact_line(contact: DocContact) -> str:
    parts = [contact.email, contact.phone, contact.location, *(link.url for link in contact.links)]
    return " | ".join(part for part in parts if part)


def education_line(entry: DocEducation) -> str:
    degree = " ".join(part for part in (entry.qualification, entry.field_of_study) if part)
    parts = [degree, entry.institution, date_range(entry.start_date, entry.end_date), entry.grade]
    return ", ".join(part for part in parts if part)


def certification_line(cert: DocCertification) -> str:
    return ", ".join(part for part in (cert.name, cert.issuer, cert.date) if part)


def role_heading(entry: DocExperience) -> str:
    head = " — ".join(part for part in (entry.title, entry.employer) if part)
    dates = date_range(entry.start_date, entry.end_date)
    return f"{head} ({dates})" if dates else head


def render_text(document: ResumeDocument) -> str:
    """Canonical Markdown-like text of a document.

    Used for scoring and matching, so the original and the rewrite are measured
    in exactly the same layout. Headings use names the section detector knows.
    """

    lines: list[str] = []
    if document.contact.name:
        lines.append(f"# {document.contact.name}")
    if contact := contact_line(document.contact):
        lines.append(contact)
    if document.summary:
        lines += ["", "## Summary", document.summary]
    if document.experience:
        lines += ["", "## Experience"]
        for entry in document.experience:
            lines.append(f"### {role_heading(entry)}")
            if entry.location:
                lines.append(entry.location)
            lines += [f"- {bullet.text}" for bullet in entry.bullets if bullet.text.strip()]
    if document.projects:
        lines += ["", "## Projects"]
        for project in document.projects:
            lines.append(f"### {project.name or 'Project'}")
            if project.description:
                lines.append(project.description)
            if project.technologies:
                lines.append("Technologies: " + ", ".join(project.technologies))
    if document.technical_skills or document.soft_skills:
        lines += ["", "## Skills"]
        if document.technical_skills:
            lines.append(", ".join(document.technical_skills))
        if document.soft_skills:
            lines.append(", ".join(document.soft_skills))
    if document.education:
        lines += ["", "## Education", *(education_line(e) for e in document.education)]
    if document.certifications:
        lines += ["", "## Certifications", *(f"- {certification_line(c)}" for c in document.certifications)]
    if document.languages:
        lines += ["", "## Languages"]
        lines.append(
            ", ".join(
                f"{lang.name} ({lang.proficiency})" if lang.proficiency else lang.name for lang in document.languages
            )
        )
    return normalize_text("\n".join(lines))


# --------------------------------------------------------------------------- conversion for scoring


def _explicit(value: str | None) -> TextField:
    return TextField(value=value, status="explicit", evidence=value) if value else TextField()


def to_structured(document: ResumeDocument, *, original: StructuredResume) -> StructuredResume:
    """A ``StructuredResume`` view of a document, so the existing scoring and matching engines can measure it.

    Soft skills keep the evidence recorded at extraction time when the name is
    unchanged (the matching engine credits soft skills demonstrated by a quoted
    sentence).
    """

    soft_evidence = {s.name.lower(): s for s in original.soft_skills}
    experience = []
    for entry in document.experience:
        structured_entry = ExperienceEntry(
            title=_explicit(entry.title),
            employer=_explicit(entry.employer),
            location=_explicit(entry.location),
            start_date=_explicit(entry.start_date),
            end_date=_explicit(entry.end_date),
            is_current=is_present(entry.end_date) if entry.end_date else None,
        )
        for bullet in entry.bullets:
            if not bullet.text.strip():
                continue
            metrics = find_metrics(bullet.text)
            item = Bullet(text=bullet.text, kind="achievement" if metrics else "responsibility", metrics=metrics)
            (structured_entry.achievements if metrics else structured_entry.responsibilities).append(item)
        experience.append(structured_entry)

    return StructuredResume(
        contact=Contact(
            name=_explicit(document.contact.name),
            email=_explicit(document.contact.email),
            phone=_explicit(document.contact.phone),
            location=_explicit(document.contact.location),
            links=[Link(kind=link.kind, url=link.url) for link in document.contact.links],
        ),
        summary=_explicit(document.summary),
        experience=experience,
        education=[
            EducationEntry(
                institution=_explicit(e.institution),
                qualification=_explicit(e.qualification),
                field_of_study=_explicit(e.field_of_study),
                start_date=_explicit(e.start_date),
                end_date=_explicit(e.end_date),
                grade=_explicit(e.grade),
            )
            for e in document.education
        ],
        technical_skills=[Skill(name=name, status="explicit") for name in document.technical_skills],
        soft_skills=[
            soft_evidence[name.lower()]
            if name.lower() in soft_evidence
            else Skill(name=name, status="explicit", evidence=None)
            for name in document.soft_skills
        ],
        certifications=[
            Certification(name=_explicit(c.name), issuer=_explicit(c.issuer), date=_explicit(c.date))
            for c in document.certifications
        ],
        projects=[
            Project(name=_explicit(p.name), description=_explicit(p.description), technologies=list(p.technologies))
            for p in document.projects
        ],
        languages=[Language(name=lang.name, proficiency=_explicit(lang.proficiency)) for lang in document.languages],
        extraction=ExtractionInfo(
            provider=original.extraction.provider, prompt_version=original.extraction.prompt_version
        ),
    )
