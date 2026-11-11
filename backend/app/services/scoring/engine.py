"""Deterministic, job-independent resume quality scoring.

Inputs are the extracted document, its detected sections and the *verified*
structured resume. The AI never supplies a number: it only proposes structure
that is checked against the source text before it reaches this module.

Each dimension starts at 100 and loses points through named deductions. The
overall score is the weighted average of the dimension scores. The ATS score
is computed separately from pass/fail parseability checks. No job description
is involved, so a resume's quality score does not depend on which job it
targets. Methodology: docs/scoring-methodology.md.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise

from app.parsing.files import ExtractedDocument
from app.parsing.normalize import word_count
from app.parsing.sections import DocumentLayout, SectionKind
from app.parsing.signals import date_style, find_emails, is_present, parse_date
from app.schemas.resume import Bullet, StructuredResume, TextField
from app.schemas.scoring import (
    AtsCheck,
    Deduction,
    DimensionKey,
    DimensionScore,
    QualityMetrics,
    QualityReport,
    Recommendation,
)
from app.services.scoring.config import DEFAULT_CONFIG, DIMENSION_LABELS, ScoringConfig
from app.services.scoring.lexicon import ACTION_VERBS, BUZZWORDS, FIRST_PERSON, WEAK_PHRASES

_WORD = re.compile(r"[A-Za-z][A-Za-z'\u2019-]*")
_PASSIVE = re.compile(r"\b(?:was|were|been|being|is|are)\s+\w+ed\b", re.IGNORECASE)


@dataclass
class ScoringInput:
    document: ExtractedDocument
    layout: DocumentLayout
    structured: StructuredResume


@dataclass
class _Dimension:
    key: DimensionKey
    deductions: list[Deduction] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)

    def deduct(self, code: str, points: int, message: str, recommendation: str, evidence: str | None = None) -> None:
        if points > 0:
            self.deductions.append(
                Deduction(code=code, points=points, message=message, recommendation=recommendation, evidence=evidence)
            )

    @property
    def score(self) -> int:
        return max(0, 100 - sum(d.points for d in self.deductions))


def _capped(per_item: int, count: int, cap: int) -> int:
    return min(per_item * count, cap)


# --------------------------------------------------------------------------- text helpers


def _first_word(text: str) -> str:
    match = _WORD.search(text)
    return match.group(0).lower() if match else ""


def _syllables(word: str) -> int:
    word = word.lower().strip("'\u2019-")
    if not word:
        return 0
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and not word.endswith(("le", "ee", "ye")) and count > 1:
        count -= 1
    return max(1, count)


def _sentences(texts: list[str]) -> list[str]:
    sentences: list[str] = []
    for text in texts:
        sentences.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if _WORD.search(part))
    return sentences


def reading_ease(sentences: list[str]) -> float | None:
    """Flesch Reading Ease (higher = easier). ``None`` when there is nothing to measure."""

    words = [w for sentence in sentences for w in _WORD.findall(sentence)]
    if not sentences or not words:
        return None
    syllables = sum(_syllables(w) for w in words)
    return round(206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syllables / len(words)), 1)


def _mentions(haystack: str, needle: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(needle.lower()) + r"(?![a-z0-9])", haystack.lower()) is not None


def _snippet(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------- dimensions


def _contact(data: ScoringInput) -> _Dimension:
    dim = _Dimension("contact")
    contact = data.structured.contact
    if not contact.name.present:
        dim.deduct(
            "contact.name_missing",
            20,
            "Your name could not be identified at the top of the resume.",
            "Put your full name on the first line, on its own.",
        )
    if not contact.email.present:
        dim.deduct(
            "contact.email_missing",
            40,
            "No email address found.",
            "Add a professional email address under your name.",
        )
    if not contact.phone.present:
        dim.deduct("contact.phone_missing", 20, "No phone number found.", "Add a phone number with country code.")
    if not contact.links:
        dim.deduct(
            "contact.links_missing",
            10,
            "No LinkedIn, GitHub or portfolio link found.",
            "Add a LinkedIn profile or portfolio link if you have one.",
        )
    if not contact.location.present:
        dim.deduct(
            "contact.location_missing",
            10,
            "No location found.",
            "Add your city and country (a full street address is not needed).",
        )
    if not dim.deductions:
        dim.strengths.append("Complete contact details: name, email, phone, location and a professional link.")
    return dim


def _structure(data: ScoringInput, config: ScoringConfig, words: int) -> _Dimension:
    dim = _Dimension("structure")
    layout, structured = data.layout, data.structured
    has_experience = layout.has("experience") or bool(structured.experience)
    if not has_experience:
        if structured.projects:
            dim.deduct(
                "structure.experience_missing",
                20,
                "No work experience section; projects are shown instead.",
                "If you have any work experience (including internships or part-time roles), "
                "add an Experience section.",
            )
        else:
            dim.deduct(
                "structure.experience_missing",
                35,
                "No work experience section found.",
                "Add an Experience section with your roles, employers and dates.",
            )
    if not layout.has("education") and not structured.education:
        dim.deduct(
            "structure.education_missing",
            20,
            "No education section found.",
            "Add an Education section (or relevant training) with qualification, institution and dates.",
        )
    if not layout.has("skills") and len(structured.technical_skills) < 3:
        dim.deduct(
            "structure.skills_missing",
            15,
            "No skills section found.",
            "Add a Skills section listing your key tools and technologies.",
        )

    if words < config.words_very_short:
        dim.deduct(
            "structure.too_short",
            40,
            f"The resume is very short ({words} words).",
            "Describe your experience in more detail; most resumes need 300-800 words.",
        )
    elif words < config.words_short:
        dim.deduct(
            "structure.short",
            10,
            f"The resume is short ({words} words).",
            "Add more detail about what you did and achieved in each role.",
        )
    elif words > config.words_very_long:
        dim.deduct(
            "structure.too_long",
            25,
            f"The resume is very long ({words} words).",
            "Cut it to the most relevant 1-2 pages; summarise older roles in one line each.",
        )
    elif words > config.words_long:
        dim.deduct(
            "structure.long",
            15,
            f"The resume is long ({words} words).",
            "Trim older or less relevant detail to keep it to about two pages.",
        )

    if layout.has("experience") and layout.has("education") and layout.has("skills"):
        dim.strengths.append("Uses clear, standard section headings (Experience, Education, Skills).")
    return dim


def _summary(data: ScoringInput, config: ScoringConfig) -> _Dimension:
    dim = _Dimension("summary")
    text = data.structured.summary.value if data.structured.summary.present else data.layout.text_of("summary")
    if not text:
        dim.deduct(
            "summary.missing",
            60,
            "No professional summary.",
            "Add a 2-4 sentence summary: your role, years of experience, core skills and what you are known for.",
        )
        return dim

    words = _WORD.findall(text)
    lowered = [w.lower() for w in words]
    if len(words) < config.summary_min_words:
        dim.deduct(
            "summary.too_short",
            25,
            f"The summary is very short ({len(words)} words).",
            "Expand it to 2-4 sentences covering your role, experience level and strongest skills.",
            _snippet(text),
        )
    elif len(words) > config.summary_max_words:
        dim.deduct(
            "summary.too_long",
            20,
            f"The summary is long ({len(words)} words).",
            "Keep the summary to 2-4 sentences; move details into your experience bullets.",
        )

    pronouns = sum(1 for w in lowered if w in FIRST_PERSON)
    if pronouns >= 2:
        dim.deduct(
            "summary.first_person",
            10,
            f"The summary uses first-person pronouns {pronouns} times.",
            "Write in implied first person: 'Backend engineer with...' rather than 'I am a backend engineer...'.",
        )

    buzzwords = [phrase for phrase in BUZZWORDS if _mentions(text, phrase)]
    if len(buzzwords) >= 2:
        dim.deduct(
            "summary.buzzwords",
            15,
            "The summary relies on generic phrases: " + ", ".join(buzzwords) + ".",
            "Replace generic adjectives with specifics: technologies, domains, scale or results.",
        )

    skill_mentioned = any(_mentions(text, skill.name) for skill in data.structured.technical_skills)
    if not re.search(r"\d", text) and not skill_mentioned:
        dim.deduct(
            "summary.generic",
            10,
            "The summary has no concrete detail (no skills, numbers or experience level).",
            "Mention your experience level and two or three of your strongest, real skills.",
        )
    if not dim.deductions:
        dim.strengths.append("A concise, specific professional summary.")
    return dim


def _all_bullets(structured: StructuredResume) -> list[Bullet]:
    return [bullet for entry in structured.experience for bullet in entry.bullets]


def _experience(data: ScoringInput, config: ScoringConfig) -> _Dimension:
    dim = _Dimension("experience")
    entries = data.structured.experience
    if not entries:
        if data.structured.projects:
            dim.deduct(
                "experience.none",
                50,
                "No work experience entries were found; projects are shown instead.",
                "Add any work experience you have, including internships, freelance or volunteer roles.",
            )
        else:
            dim.deduct(
                "experience.none",
                100,
                "No work experience entries were found.",
                "Add your roles with job title, employer, dates and 2-6 bullets each.",
            )
        return dim

    def label(index: int) -> str:
        entry = entries[index]
        return entry.title.value or entry.employer.value or f"role {index + 1}"

    missing_title = [label(i) for i, e in enumerate(entries) if not e.title.present]
    missing_employer = [label(i) for i, e in enumerate(entries) if not e.employer.present]
    missing_dates = [label(i) for i, e in enumerate(entries) if not e.start_date.present]
    few_bullets = [label(i) for i, e in enumerate(entries) if len(e.bullets) < config.min_bullets_per_role]
    many_bullets = [label(i) for i, e in enumerate(entries) if len(e.bullets) > config.max_bullets_per_role]

    if missing_title:
        dim.deduct(
            "experience.title_missing",
            _capped(10, len(missing_title), 30),
            f"{len(missing_title)} role(s) have no clear job title: " + ", ".join(missing_title) + ".",
            "Give every role a job title on its own line.",
        )
    if missing_employer:
        dim.deduct(
            "experience.employer_missing",
            _capped(10, len(missing_employer), 30),
            f"{len(missing_employer)} role(s) have no employer: " + ", ".join(missing_employer) + ".",
            "Name the employer (or 'Freelance' / 'Self-employed') for every role.",
        )
    if missing_dates:
        dim.deduct(
            "experience.dates_missing",
            _capped(8, len(missing_dates), 24),
            f"{len(missing_dates)} role(s) have no start date: " + ", ".join(missing_dates) + ".",
            "Add start and end dates (month and year) to every role.",
        )
    if few_bullets:
        dim.deduct(
            "experience.few_bullets",
            _capped(8, len(few_bullets), 24),
            f"{len(few_bullets)} role(s) have fewer than {config.min_bullets_per_role} bullet points: "
            + ", ".join(few_bullets)
            + ".",
            "Describe each role with 2-6 bullets covering what you did and what changed as a result.",
        )
    if many_bullets:
        dim.deduct(
            "experience.many_bullets",
            _capped(5, len(many_bullets), 15),
            f"{len(many_bullets)} role(s) have more than {config.max_bullets_per_role} bullets.",
            "Keep the 4-6 most important bullets per role.",
        )

    bullets = _all_bullets(data.structured)
    if len(bullets) < config.min_total_bullets:
        dim.deduct(
            "experience.thin",
            15,
            f"Only {len(bullets)} experience bullet(s) in total.",
            "Add bullets describing your main responsibilities and results in each role.",
        )
    if bullets:
        verbs = [_first_word(b.text) for b in bullets]
        ratio = sum(1 for v in verbs if v in ACTION_VERBS) / len(bullets)
        if ratio < config.action_verb_ratio_poor:
            dim.deduct(
                "experience.action_verbs_poor",
                15,
                f"Only {ratio:.0%} of bullets start with an action verb.",
                "Start each bullet with a strong past-tense verb (Led, Built, Reduced, Launched...).",
            )
        elif ratio < config.action_verb_ratio_good:
            dim.deduct(
                "experience.action_verbs",
                8,
                f"{ratio:.0%} of bullets start with an action verb.",
                "Start more bullets with a strong action verb.",
            )
        else:
            dim.strengths.append(f"{ratio:.0%} of experience bullets start with an action verb.")

        weak = [b.text for b in bullets if any(phrase in b.text.lower() for phrase in WEAK_PHRASES)]
        if weak:
            dim.deduct(
                "experience.weak_phrases",
                _capped(4, len(weak), 16),
                f"{len(weak)} bullet(s) use passive duty phrases such as 'responsible for'.",
                "Rewrite duty statements as actions: 'Managed...' instead of 'Responsible for managing...'.",
                _snippet(weak[0]),
            )

        average = sum(len(_WORD.findall(b.text)) for b in bullets) / len(bullets)
        if average > config.bullet_words_max_avg:
            dim.deduct(
                "experience.long_bullets",
                10,
                f"Bullets average {average:.0f} words.",
                "Keep bullets to one or two lines (about 15-30 words).",
            )
        elif average < config.bullet_words_min_avg:
            dim.deduct(
                "experience.thin_bullets",
                8,
                f"Bullets average only {average:.0f} words.",
                "Add what you did, how, and the result to each bullet.",
            )

    starts = [parse_date(e.start_date.value) for e in entries if e.start_date.present]
    ordered = [s for s in starts if s is not None]
    if len(ordered) >= 2 and any(earlier < later for earlier, later in pairwise(ordered)):
        dim.deduct(
            "experience.order", 5, "Roles are not in reverse-chronological order.", "List your most recent role first."
        )
    reversed_ranges = [
        label(i)
        for i, e in enumerate(entries)
        if e.start_date.present
        and e.end_date.present
        and not is_present(e.end_date.value)
        and (start := parse_date(e.start_date.value))
        and (end := parse_date(e.end_date.value))
        and end < start
    ]
    if reversed_ranges:
        dim.deduct(
            "experience.date_range",
            _capped(5, len(reversed_ranges), 10),
            "End date is before start date for: " + ", ".join(reversed_ranges) + ".",
            "Check the dates for these roles.",
        )
    return dim


def _achievements(data: ScoringInput, config: ScoringConfig) -> _Dimension:
    dim = _Dimension("achievements")
    bullets = _all_bullets(data.structured)
    if not bullets:
        dim.deduct(
            "achievements.no_bullets",
            70,
            "There are no experience bullets to show your impact.",
            "Add bullets to each role describing results you achieved.",
        )
        return dim

    quantified = [b for b in bullets if b.metrics]
    ratio = len(quantified) / len(bullets)
    for threshold, points in config.quantified_bands:
        if ratio >= threshold:
            if points:
                dim.deduct(
                    "achievements.quantified",
                    points,
                    f"{len(quantified)} of {len(bullets)} bullets ({ratio:.0%}) include a measurable result.",
                    "Where you have real figures (team size, volume, time or money saved, growth), add them. "
                    "Do not estimate numbers you cannot support.",
                )
            break
    if not any(b.kind == "achievement" for b in bullets):
        dim.deduct(
            "achievements.none",
            10,
            "Bullets describe duties but not outcomes.",
            "For each role, add at least one bullet about a result: what improved because of your work.",
        )
    for example in quantified[:2]:
        dim.strengths.append(f'Quantified result: "{_snippet(example.text)}"')
    return dim


def _skills(data: ScoringInput, config: ScoringConfig) -> _Dimension:
    dim = _Dimension("skills")
    skills = data.structured.technical_skills
    count = len(skills)
    if count == 0:
        dim.deduct(
            "skills.none",
            60,
            "No technical skills or tools were found.",
            "Add a Skills section listing the tools, technologies and methods you actually use.",
        )
        return dim
    if count < config.skills_few:
        dim.deduct(
            "skills.few",
            25,
            f"Only {count} technical skill(s) listed.",
            "List the tools and technologies you genuinely use (typically 8-20).",
        )
    elif count > config.skills_many:
        dim.deduct(
            "skills.too_many",
            15,
            f"{count} skills listed; long lists dilute the important ones.",
            "Keep the skills you are strongest in and group them (Languages, Frameworks, Tools).",
        )

    narrative = " ".join(
        [b.text for b in _all_bullets(data.structured)]
        + [p.description.value or "" for p in data.structured.projects]
        + [" ".join(p.technologies) for p in data.structured.projects]
        + [data.structured.summary.value or ""]
    )
    evidenced = [s.name for s in skills if _mentions(narrative, s.name)]
    if count >= config.skills_few:
        ratio = len(evidenced) / count
        if ratio < config.skills_evidenced_ratio_min:
            dim.deduct(
                "skills.unevidenced",
                15,
                f"Only {len(evidenced)} of {count} listed skills appear in your experience or projects.",
                "Show where you used your key skills in your experience or project bullets.",
            )
        elif evidenced:
            dim.strengths.append(f"{len(evidenced)} listed skills are backed up in your experience or projects.")
    if data.structured.soft_skills:
        dim.strengths.append("Soft skills: " + ", ".join(s.name for s in data.structured.soft_skills[:5]) + ".")
    return dim


def _education(data: ScoringInput) -> _Dimension:
    dim = _Dimension("education")
    entries = data.structured.education
    if not entries:
        points = 40 if data.structured.certifications else 60
        dim.deduct(
            "education.none",
            points,
            "No education entries were found.",
            "Add your highest qualification or relevant training. "
            "If you have none, list relevant courses or certifications.",
        )
        return dim
    no_qualification = sum(1 for e in entries if not e.qualification.present)
    no_institution = sum(1 for e in entries if not e.institution.present)
    no_dates = sum(1 for e in entries if not e.start_date.present and not e.end_date.present)
    if no_qualification:
        dim.deduct(
            "education.qualification_missing",
            _capped(15, no_qualification, 30),
            f"{no_qualification} education entr(y/ies) have no qualification.",
            "State the qualification for each entry (e.g. BSc Computer Science).",
        )
    if no_institution:
        dim.deduct(
            "education.institution_missing",
            _capped(15, no_institution, 30),
            f"{no_institution} education entr(y/ies) have no institution.",
            "Name the institution for each entry.",
        )
    if no_dates:
        dim.deduct(
            "education.dates_missing",
            _capped(10, no_dates, 20),
            f"{no_dates} education entr(y/ies) have no dates.",
            "Add the year you graduated (or expect to).",
        )
    if not dim.deductions:
        dim.strengths.append("Education entries are complete.")
    return dim


def _explicit_dates(structured: StructuredResume) -> list[str]:
    fields: list[TextField] = []
    for entry in structured.experience:
        fields += [entry.start_date, entry.end_date]
    for edu in structured.education:
        fields += [edu.start_date, edu.end_date]
    return [f.value for f in fields if f.present and f.value and not is_present(f.value)]


def _special_char_count(text: str) -> int:
    return sum(
        1 for ch in text if unicodedata.category(ch) == "So" or 0xE000 <= ord(ch) <= 0xF8FF or ord(ch) >= 0x1F000
    )


def _formatting(data: ScoringInput) -> _Dimension:
    dim = _Dimension("formatting")
    styles = sorted({style for value in _explicit_dates(data.structured) if (style := date_style(value))})
    if len(styles) > 1:
        dim.deduct(
            "formatting.date_styles",
            15,
            "Dates use mixed formats: " + ", ".join(styles) + ".",
            "Use one date format throughout, e.g. 'Jan 2021 - Mar 2023'.",
        )

    paragraphs = [
        line
        for line in data.layout.text_of("experience").split("\n")
        if line and not line.startswith(("- ", "#")) and len(_WORD.findall(line)) > 50
    ]
    if paragraphs:
        dim.deduct(
            "formatting.paragraphs",
            _capped(10, len(paragraphs), 20),
            f"{len(paragraphs)} long paragraph(s) in the experience section.",
            "Break long paragraphs into bullet points.",
            _snippet(paragraphs[0]),
        )

    shouting = [
        line
        for line in data.document.text.split("\n")
        if not line.startswith("#")
        and len(_WORD.findall(line)) > 4
        and line.upper() == line
        and re.search(r"[A-Z]", line)
    ]
    if shouting:
        dim.deduct(
            "formatting.all_caps",
            _capped(5, len(shouting), 10),
            f"{len(shouting)} line(s) of body text are in capitals.",
            "Use capitals only for headings.",
            _snippet(shouting[0]),
        )

    specials = _special_char_count(data.document.text)
    if specials > 10:
        dim.deduct(
            "formatting.symbols",
            10,
            f"{specials} decorative symbols or icons found.",
            "Replace icons and symbols with plain text labels.",
        )
    if not dim.deductions:
        dim.strengths.append("Consistent dates and clean, bullet-based formatting.")
    return dim


def _readability(data: ScoringInput, config: ScoringConfig) -> tuple[_Dimension, float | None]:
    dim = _Dimension("readability")
    bullets = _all_bullets(data.structured)
    texts = [b.text for b in bullets]
    if data.structured.summary.present and data.structured.summary.value:
        texts.append(data.structured.summary.value)
    sentences = _sentences(texts)
    ease = reading_ease(sentences)
    if ease is None:
        return dim, None

    if ease < config.reading_ease_very_hard:
        dim.deduct(
            "readability.very_hard",
            25,
            f"Text is very dense (reading ease {ease:.0f}/100).",
            "Use shorter sentences and plainer words.",
        )
    elif ease < config.reading_ease_hard:
        dim.deduct(
            "readability.hard",
            12,
            f"Text is dense (reading ease {ease:.0f}/100).",
            "Shorten long sentences and split compound bullets.",
        )

    words_per_sentence = sum(len(_WORD.findall(s)) for s in sentences) / len(sentences)
    if words_per_sentence > config.sentence_words_very_long:
        dim.deduct(
            "readability.long_sentences",
            15,
            f"Sentences average {words_per_sentence:.0f} words.",
            "Aim for 15-25 words per sentence or bullet.",
        )
    elif words_per_sentence > config.sentence_words_long:
        dim.deduct(
            "readability.longish_sentences",
            8,
            f"Sentences average {words_per_sentence:.0f} words.",
            "Tighten sentences to under 25 words.",
        )

    if bullets:
        passive = sum(1 for b in bullets if _PASSIVE.search(b.text))
        if passive / len(bullets) > 0.3:
            dim.deduct(
                "readability.passive",
                10,
                f"{passive} bullet(s) use passive voice.",
                "Use active voice: 'Reduced costs by...' instead of 'Costs were reduced...'.",
            )
        repeated = [
            verb for verb, n in Counter(_first_word(b.text) for b in bullets).items() if verb in ACTION_VERBS and n >= 4
        ]
        if repeated:
            dim.deduct(
                "readability.repeated_verbs",
                _capped(5, len(repeated), 15),
                "Repeated opening verbs: " + ", ".join(repeated) + ".",
                "Vary the verbs that open your bullets.",
            )
    if not dim.deductions:
        dim.strengths.append("Clear, readable sentences.")
    return dim, ease


# --------------------------------------------------------------------------- ATS


def _ats_checks(data: ScoringInput, words: int) -> list[AtsCheck]:
    document, layout, structured = data.document, data.layout, data.structured
    checks: list[AtsCheck] = [
        AtsCheck(code="ats.text_layer", passed=True, points=30, message="Text can be extracted from the document."),
    ]

    checks.append(
        AtsCheck(
            code="ats.image_pages",
            passed=not document.pages_without_text,
            points=20,
            message="All pages contain selectable text."
            if not document.pages_without_text
            else "Some pages appear to be images: " + ", ".join(map(str, document.pages_without_text)) + ".",
            recommendation=None
            if not document.pages_without_text
            else "Export the resume as a text-based PDF or DOCX.",
        )
    )

    standard: tuple[tuple[str, SectionKind], ...] = (
        ("Experience", "experience"),
        ("Education", "education"),
        ("Skills", "skills"),
    )
    missing = [name for name, kind in standard if not layout.has(kind)]
    checks.append(
        AtsCheck(
            code="ats.standard_headings",
            passed=not missing,
            points=min(10 * len(missing), 30) if missing else 10,
            message="Standard section headings found."
            if not missing
            else "Missing standard headings: " + ", ".join(missing) + ".",
            recommendation=None
            if not missing
            else "Use conventional headings such as 'Experience', 'Education' and 'Skills'.",
        )
    )

    header_only = bool(
        document.format == "docx"
        and document.page_header_text
        and find_emails(document.page_header_text)
        and not find_emails(document.body_text)
    )
    checks.append(
        AtsCheck(
            code="ats.contact_in_body",
            passed=not header_only,
            points=15,
            message="Contact details are in the main body."
            if not header_only
            else "Contact details are only in the page header, which some ATS ignore.",
            recommendation=None
            if not header_only
            else "Move your email and phone number into the main body of the document.",
        )
    )

    checks.append(
        AtsCheck(
            code="ats.tables",
            passed=document.table_count == 0,
            points=15,
            message="No tables used."
            if document.table_count == 0
            else f"{document.table_count} table(s) used for layout.",
            recommendation=None
            if document.table_count == 0
            else "Replace tables with plain headings and bullets; some ATS read table cells out of order.",
        )
    )

    accepted = document.format in ("pdf", "docx")
    checks.append(
        AtsCheck(
            code="ats.file_format",
            passed=accepted,
            points=10,
            message="PDF/DOCX are widely accepted." if accepted else "Markdown files are not accepted by most ATS.",
            recommendation=None if accepted else "Export the resume to PDF or DOCX before applying.",
        )
    )

    specials = _special_char_count(document.text)
    checks.append(
        AtsCheck(
            code="ats.symbols",
            passed=specials <= 5,
            points=10,
            message="No icon fonts or decorative symbols." if specials <= 5 else f"{specials} icons or symbols found.",
            recommendation=None
            if specials <= 5
            else "Replace icons (phone, email, location symbols) with text labels.",
        )
    )

    undated = [e for e in structured.experience if not (e.start_date.present and parse_date(e.start_date.value))]
    checks.append(
        AtsCheck(
            code="ats.dates",
            passed=not undated,
            points=10,
            message="Every role has a recognisable start date."
            if not undated
            else f"{len(undated)} role(s) have no recognisable start date.",
            recommendation=None
            if not undated
            else "Write dates as 'Jan 2021' or '01/2021' so they are parsed correctly.",
        )
    )

    too_long = (document.page_count or 0) > 3 or words > 1800
    checks.append(
        AtsCheck(
            code="ats.length",
            passed=not too_long,
            points=5,
            message="Length is within normal limits." if not too_long else "The document is longer than three pages.",
            recommendation=None if not too_long else "Keep the resume to two pages where possible.",
        )
    )
    return checks


# --------------------------------------------------------------------------- assembly


def _missing_information(structured: StructuredResume) -> list[str]:
    missing = []
    contact = structured.contact
    for label, value in (
        ("Name", contact.name),
        ("Email address", contact.email),
        ("Phone number", contact.phone),
        ("Location", contact.location),
    ):
        if not value.present:
            missing.append(label)
    if not structured.summary.present:
        missing.append("Professional summary")
    if not structured.experience:
        missing.append("Work experience")
    for entry in structured.experience:
        name = entry.title.value or entry.employer.value or "A role"
        gaps = [
            label
            for label, value in (
                ("job title", entry.title),
                ("employer", entry.employer),
                ("start date", entry.start_date),
                ("end date", entry.end_date),
            )
            if not value.present
        ]
        if gaps:
            missing.append(f"{name}: " + ", ".join(gaps))
    if not structured.education:
        missing.append("Education")
    if not structured.technical_skills:
        missing.append("Technical skills")
    return missing


def score_resume(data: ScoringInput, config: ScoringConfig = DEFAULT_CONFIG) -> QualityReport:
    words = word_count(data.document.text)
    readability, ease = _readability(data, config)
    dimensions = [
        _contact(data),
        _structure(data, config, words),
        _summary(data, config),
        _experience(data, config),
        _achievements(data, config),
        _skills(data, config),
        _education(data),
        _formatting(data),
        readability,
    ]

    scored = [
        DimensionScore(
            key=dim.key,
            label=DIMENSION_LABELS[dim.key],
            weight=config.weights[dim.key],
            score=dim.score,
            contribution=round(config.weights[dim.key] * dim.score / 100, 2),
            deductions=dim.deductions,
            strengths=dim.strengths,
        )
        for dim in dimensions
    ]
    exact_total = sum(config.weights[dim.key] * dim.score for dim in dimensions) / 100
    overall = int(exact_total + 0.5)  # round half up, deterministic
    score_cap = None
    if words < config.words_very_short and overall > config.very_short_score_cap:
        overall = config.very_short_score_cap
        score_cap = (
            f"Capped at {config.very_short_score_cap}: the resume has only {words} words, too little to show "
            "the depth of your experience, however well written."
        )

    ats_checks = _ats_checks(data, words)
    ats_score = max(0, 100 - sum(check.points for check in ats_checks if not check.passed))

    recommendations = sorted(
        (
            Recommendation(
                dimension=dim.key,
                message=deduction.message,
                recommendation=deduction.recommendation,
                impact=round(deduction.points * config.weights[dim.key] / 100, 1),
            )
            for dim in dimensions
            for deduction in dim.deductions
        ),
        key=lambda rec: (-rec.impact, rec.dimension, rec.message),
    )

    bullets = _all_bullets(data.structured)
    metrics = QualityMetrics(
        word_count=words,
        bullet_count=len(bullets),
        quantified_bullet_ratio=round(sum(1 for b in bullets if b.metrics) / len(bullets), 3) if bullets else 0.0,
        action_verb_ratio=round(sum(1 for b in bullets if _first_word(b.text) in ACTION_VERBS) / len(bullets), 3)
        if bullets
        else 0.0,
        reading_ease=ease,
        experience_entries=len(data.structured.experience),
        technical_skill_count=len(data.structured.technical_skills),
    )

    return QualityReport(
        scoring_version=config.version,
        overall_score=overall,
        label=config.label_for(overall),
        ats_score=ats_score,
        ats_checks=ats_checks,
        dimensions=scored,
        strengths=[s for dim in dimensions for s in dim.strengths][:8],
        weaknesses=[rec.message for rec in recommendations[:5]],
        missing_information=_missing_information(data.structured),
        recommendations=recommendations,
        metrics=metrics,
        score_cap=score_cap,
    )
