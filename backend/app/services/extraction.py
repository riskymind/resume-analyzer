"""Structured resume extraction: AI proposes, application code verifies.

1. The provider returns JSON describing the resume (``AIResumeExtraction``).
2. The JSON is validated against the schema; malformed output is a 502.
3. Every proposed value is checked against the normalised resume text. A
   value is ``explicit`` only if it appears in the resume; ``inferred`` only
   for the few field types where inference is allowed *and* a verbatim
   supporting quote is found. Anything else is discarded and counted in
   ``extraction.removed_items``, so the model cannot add facts.
4. Contact details (email, phone, links) come from deterministic parsing,
   not from the model.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from app.ai.base import AIProvider, AIProviderError
from app.ai.prompts import PROMPT_VERSION_RESUME_EXTRACTION, build_resume_extraction_prompt
from app.ai.structured import parse_model_output, response_schema
from app.core.errors import AIUpstreamError
from app.parsing.sections import DocumentLayout
from app.parsing.signals import find_emails, find_links, find_metrics, find_phones, guess_name, is_present
from app.schemas.resume import (
    AIEducation,
    AIExperience,
    AIResumeExtraction,
    AIValue,
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

logger = logging.getLogger(__name__)

# Output cap for one extraction (thinking tokens included). A 40 000-character resume quoted back as
# evidence needs well under half of this; hitting it means a runaway reply, which fails cleanly.
MAX_OUTPUT_TOKENS_RESUME_EXTRACTION = 32_768

_MAX_TEXT_FIELD = 2000  # summaries and project descriptions
_MAX_VALUE_CHARS = 300  # longer "values" (except summary/description/bullets) are not plausible fields


def _match_key(text: str) -> str:
    """Comparison form: NFKC, lowercase, unified dashes/quotes, no markdown or bullet markers."""

    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]", "-", text)
    text = re.sub(r"[\u2018\u2019\u201a\u2032]", "'", text).replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"(?m)^\s*(?:#{1,6}|-)\s+", " ", text)
    text = re.sub(r"[*_`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class SourceText:
    """The resume text in comparison form, with word-boundary-aware lookup."""

    def __init__(self, text: str) -> None:
        self.key = _match_key(text)

    def contains(self, snippet: str | None) -> bool:
        if not snippet:
            return False
        needle = _match_key(snippet)
        if len(needle) < 2:
            return False
        pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
        return re.search(pattern, self.key) is not None


@dataclass
class _Tally:
    removed: int = 0

    def drop(self, count: int = 1) -> None:
        self.removed += count


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip().strip("-•*").strip()
    return cleaned or None


def _field(
    raw: AIValue | None,
    source: SourceText,
    tally: _Tally,
    *,
    allow_inferred: bool = False,
    max_chars: int = _MAX_VALUE_CHARS,
) -> TextField:
    if raw is None:
        return TextField()
    value = _clean(raw.value)
    if value is None:
        return TextField()
    evidence = _clean(raw.evidence)
    if len(value) <= max_chars and source.contains(value):
        return TextField(value=value, status="explicit", evidence=evidence if source.contains(evidence) else value)
    if allow_inferred and len(value) <= 120 and evidence and source.contains(evidence):
        return TextField(value=value, status="inferred", evidence=evidence)
    tally.drop()
    return TextField()


def _experience(raw: AIExperience, source: SourceText, tally: _Tally) -> ExperienceEntry | None:
    entry = ExperienceEntry(
        title=_field(raw.title, source, tally),
        employer=_field(raw.employer, source, tally),
        location=_field(raw.location, source, tally, allow_inferred=True),
        start_date=_field(raw.start_date, source, tally, max_chars=40),
        end_date=_field(raw.end_date, source, tally, max_chars=40),
    )
    if not entry.title.present and not entry.employer.present:
        tally.drop()
        return None
    if entry.end_date.present:
        entry.is_current = is_present(entry.end_date.value)

    seen: set[str] = set()
    for bullet in raw.bullets:
        text = _clean(bullet.text)
        if not text or not source.contains(text):
            tally.drop()
            continue
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        item = Bullet(text=text, kind=bullet.type, metrics=find_metrics(text))
        (entry.achievements if bullet.type == "achievement" else entry.responsibilities).append(item)
    return entry


def _education(raw: AIEducation, source: SourceText, tally: _Tally) -> EducationEntry | None:
    entry = EducationEntry(
        institution=_field(raw.institution, source, tally),
        qualification=_field(raw.qualification, source, tally),
        field_of_study=_field(raw.field_of_study, source, tally),
        start_date=_field(raw.start_date, source, tally, max_chars=40),
        end_date=_field(raw.end_date, source, tally, max_chars=40),
        grade=_field(raw.grade, source, tally, max_chars=60),
    )
    if not entry.institution.present and not entry.qualification.present:
        tally.drop()
        return None
    return entry


def _skills(raw_skills: list, source: SourceText, tally: _Tally, *, allow_inferred: bool) -> list[Skill]:  # type: ignore[type-arg]
    skills: list[Skill] = []
    seen: set[str] = set()
    for raw in raw_skills:
        name = _clean(raw.name)
        if not name or len(name) > 60 or name.lower() in seen:
            continue
        evidence = _clean(raw.evidence)
        if source.contains(name):
            skills.append(Skill(name=name, status="explicit", evidence=evidence if source.contains(evidence) else None))
        elif allow_inferred and evidence and source.contains(evidence):
            skills.append(Skill(name=name, status="inferred", evidence=evidence))
        else:
            tally.drop()
            continue
        seen.add(name.lower())
    return skills


def build_structured_resume(
    raw: AIResumeExtraction,
    *,
    text: str,
    layout: DocumentLayout,
    provider_name: str,
) -> StructuredResume:
    """Verify model output against ``text`` and assemble the trusted structure."""

    source = SourceText(text)
    tally = _Tally()

    contact = Contact()
    emails = find_emails(layout.header_text) or find_emails(text)
    phones = find_phones(layout.header_text) or find_phones(layout.text_of("contact")) or find_phones(text)
    if emails:
        contact.email = TextField(value=emails[0], status="explicit", evidence=emails[0])
    if phones:
        contact.phone = TextField(value=phones[0], status="explicit", evidence=phones[0])
    contact.links = [Link(kind=link.kind, url=link.url) for link in find_links(text, header_text=layout.header_text)]

    model_name = _field(raw.name, source, tally, max_chars=80)
    heuristic_name = guess_name(layout.header_lines)
    if model_name.present:
        contact.name = model_name
    elif heuristic_name:
        # Position-based: the first header line looks like a name.
        contact.name = TextField(value=heuristic_name, status="inferred", evidence=heuristic_name)
    contact.location = _field(raw.location, source, tally, allow_inferred=True, max_chars=100)

    experience = [entry for entry in (_experience(item, source, tally) for item in raw.experience) if entry]
    education = [entry for entry in (_education(item, source, tally) for item in raw.education) if entry]

    certifications = []
    for raw_cert in raw.certifications:
        cert = Certification(
            name=_field(raw_cert.name, source, tally),
            issuer=_field(raw_cert.issuer, source, tally),
            date=_field(raw_cert.date, source, tally, max_chars=40),
        )
        if cert.name.present:
            certifications.append(cert)
        else:
            tally.drop()

    projects = []
    for raw_project in raw.projects:
        project = Project(
            name=_field(raw_project.name, source, tally, max_chars=120),
            description=_field(raw_project.description, source, tally, max_chars=_MAX_TEXT_FIELD),
            technologies=[],
        )
        for tech in raw_project.technologies:
            cleaned = _clean(tech)
            if cleaned and len(cleaned) <= 60 and source.contains(cleaned):
                project.technologies.append(cleaned)
            else:
                tally.drop()
        if project.name.present:
            projects.append(project)
        else:
            tally.drop()

    languages = []
    seen_languages: set[str] = set()
    for raw_language in raw.languages:
        name = _clean(raw_language.name)
        if name and len(name) <= 40 and source.contains(name) and name.lower() not in seen_languages:
            seen_languages.add(name.lower())
            languages.append(
                Language(
                    name=name,
                    proficiency=_field(raw_language.proficiency, source, tally, allow_inferred=True, max_chars=60),
                )
            )
        else:
            tally.drop()

    structured = StructuredResume(
        contact=contact,
        summary=_field(raw.summary, source, tally, max_chars=_MAX_TEXT_FIELD),
        experience=experience,
        education=education,
        technical_skills=_skills(raw.technical_skills, source, tally, allow_inferred=False),
        soft_skills=_skills(raw.soft_skills, source, tally, allow_inferred=True),
        certifications=certifications,
        projects=projects,
        languages=languages,
        extraction=ExtractionInfo(provider=provider_name, prompt_version=PROMPT_VERSION_RESUME_EXTRACTION),
    )
    structured.extraction.removed_items = tally.removed
    if tally.removed:
        structured.extraction.warnings.append(
            f"{tally.removed} extracted item(s) were discarded because they could not be found in the resume text."
        )
    return structured


def extract_structured_resume(provider: AIProvider, *, text: str, layout: DocumentLayout) -> StructuredResume:
    system, prompt = build_resume_extraction_prompt(text)
    try:
        raw_text = provider.generate_json(
            system=system,
            prompt=prompt,
            json_schema=response_schema(AIResumeExtraction),
            max_output_tokens=MAX_OUTPUT_TOKENS_RESUME_EXTRACTION,
            task="resume_extraction",
        )
    except AIProviderError as exc:
        raise AIUpstreamError(str(exc)) from exc

    raw = parse_model_output(
        raw_text,
        AIResumeExtraction,
        provider=provider.name,
        task="resume_extraction",
        prompt_version=PROMPT_VERSION_RESUME_EXTRACTION,
        user_message="The AI provider returned an unexpected resume extraction format.",
    )

    structured = build_structured_resume(raw, text=text, layout=layout, provider_name=provider.name)
    logger.info(
        "resume_extracted",
        extra={
            "provider": provider.name,
            "experience_entries": len(structured.experience),
            "removed_items": structured.extraction.removed_items,
        },
    )
    return structured


# Public names for the verification primitives, reused by job description extraction.
match_key = _match_key
clean_value = _clean
Tally = _Tally
verify_text_field = _field
