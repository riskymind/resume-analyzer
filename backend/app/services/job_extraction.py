"""Structured job description extraction: AI proposes, application code verifies.

1. The provider returns JSON describing the job (``AIJobExtraction``).
2. Every proposed requirement must be supported by text that actually appears
   in the job description. Technical skills and certifications must also be
   *named* in the text (directly or by a known alias), so the model cannot add
   "typical" requirements the employer never wrote. Unsupported items are
   discarded and counted.
3. Required vs preferred is decided from the job description's own wording
   where it is explicit ("Nice to have:", "... is a plus", a "Preferred
   qualifications" heading). The model's classification is used only when the
   text is ambiguous, and every requirement records which source decided.
4. Minimum years are parsed from the evidence text; a model-supplied number
   that the evidence does not state is dropped.
5. A deterministic lexicon scan adds well-known technical skills the model
   missed (``status="detected"``). Without explicit "required" wording they are
   classified as *preferred*, so passing mentions such as "our stack includes
   Go" never become mandatory requirements.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.ai.base import AIProvider, AIProviderError
from app.ai.prompts import PROMPT_VERSION_JOB_EXTRACTION, build_job_extraction_prompt
from app.ai.structured import parse_model_output, response_schema
from app.core.errors import AIUpstreamError
from app.schemas.job import (
    REQUIREMENT_CATEGORIES,
    AIJobExtraction,
    AIRequirement,
    Classification,
    ClassificationSource,
    Importance,
    JobExtractionInfo,
    JobInfo,
    JobKeyword,
    JobRequirement,
    RequirementCategory,
    StructuredJob,
)
from app.services.extraction import SourceText, Tally, clean_value, match_key, verify_text_field
from app.services.matching import skills

logger = logging.getLogger(__name__)

# Output cap for one job extraction (thinking tokens included); see extraction.py.
MAX_OUTPUT_TOKENS_JOB_EXTRACTION = 16_384

MAX_REQUIREMENTS = 80
MAX_KEYWORDS = 30

_PREFERRED_CUE = re.compile(
    r"\b(?:nice[ -]to[ -]haves?|good[ -]to[ -]haves?|preferred|preferably|prefer|(?:is |would be )?a plus|"
    r"bonus(?: points)?|desirable|desired|ideally|advantageous|an advantage|not required|optional|"
    r"would be (?:great|nice)|beneficial)\b",
    re.IGNORECASE,
)
_REQUIRED_CUE = re.compile(
    r"\b(?:required|requirements?|must[ -]haves?|must|mandatory|essential|minimum qualifications?|"
    r"basic qualifications?|qualifications|what you(?:'|\u2019)ll need|you will need|you need|need to have)\b",
    re.IGNORECASE,
)
_MD_HEADING = re.compile(r"^\s*#{1,6}\s+")
_SENTENCE_SPLIT = re.compile(r"(?<=[A-Za-z0-9)%][.;!?])\s+(?=[A-Z0-9(])|;\s+")

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "fifteen": 15,
}
_YEARS = re.compile(
    r"\b(?P<n>\d{1,2}(?:\.\d)?|" + "|".join(_NUMBER_WORDS) + r")\s*\+?\s*"
    r"(?:(?:-|\u2013|to)\s*\d{1,2}\s*\+?\s*)?(?:\(\s*\d{1,2}\s*\)\s*)?(?:years?|yrs?)\b",
    re.IGNORECASE,
)

_CATEGORY_ALIASES: dict[str, RequirementCategory] = {
    "technical": "technical_skill",
    "technical_skills": "technical_skill",
    "skill": "technical_skill",
    "hard_skill": "technical_skill",
    "tool": "technical_skill",
    "technology": "technical_skill",
    "soft": "soft_skill",
    "soft_skills": "soft_skill",
    "interpersonal": "soft_skill",
    "experiences": "experience",
    "work_experience": "experience",
    "qualification": "education",
    "degree": "education",
    "certificate": "certification",
    "certifications": "certification",
    "license": "certification",
    "responsibilities": "responsibility",
    "duty": "responsibility",
    "duties": "responsibility",
}
_IMPORTANCE: frozenset[str] = frozenset({"high", "medium", "low"})


def _category(raw: str) -> RequirementCategory | None:
    key = re.sub(r"[\s-]+", "_", raw.strip().lower())
    if key in REQUIREMENT_CATEGORIES:
        return key
    return _CATEGORY_ALIASES.get(key)


def parse_min_years(text: str | None) -> float | None:
    """The smallest number of years stated in ``text`` ("5+ years", "3-5 years", "five years")."""

    if not text:
        return None
    values: list[float] = []
    for match in _YEARS.finditer(text):
        token = match.group("n").lower()
        values.append(float(_NUMBER_WORDS[token]) if token in _NUMBER_WORDS else float(token))
    plausible = [value for value in values if 0 < value <= 40]
    return min(plausible) if plausible else None


# --------------------------------------------------------------------------- context classification


@dataclass
class _Segment:
    text: str
    key: str
    cue: Classification | None
    heading_context: Classification | None
    both_cues: bool


def _cue(text: str) -> Classification | None:
    if _PREFERRED_CUE.search(text):
        return "preferred"
    if _REQUIRED_CUE.search(text):
        return "required"
    return None


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if _MD_HEADING.match(stripped):
        return True
    words = len(stripped.split())
    if stripped.endswith(":") and words <= 10:
        return True
    letters = [c for c in stripped if c.isalpha()]
    return bool(letters) and words <= 6 and all(c.isupper() for c in letters)


class JobText:
    """The job description split into sentence segments, each tagged with its required/preferred context."""

    def __init__(self, text: str) -> None:
        self.source = SourceText(text)
        self.segments: list[_Segment] = []
        context: Classification | None = None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _is_heading(line):
                # A heading sets the context for the lines below it; one without a cue
                # (e.g. "Responsibilities") resets it.
                context = _cue(line)
                self.segments.append(_Segment(line, match_key(line), context, context, False))
                continue
            for sentence in _SENTENCE_SPLIT.split(line):
                if not sentence.strip():
                    continue
                both = bool(_PREFERRED_CUE.search(sentence) and _REQUIRED_CUE.search(sentence))
                self.segments.append(_Segment(sentence, match_key(sentence), _cue(sentence), context, both))

    def segment_for(self, snippet: str) -> _Segment | None:
        needle = match_key(snippet)
        if not needle:
            return None
        head = needle[:60]
        for segment in self.segments:
            if needle in segment.key or head in segment.key:
                return segment
        for segment in self.segments:  # evidence spanning several segments starts in this one
            if segment.key and segment.key in needle and needle.startswith(segment.key[:30]):
                return segment
        return None

    def sentence_mentioning(self, term: str) -> str | None:
        for segment in self.segments:
            if skills.mentions(segment.key, term, allow_ambiguous=True) or SourceText(segment.text).contains(term):
                return segment.text.strip()
        return None

    def classify(self, evidence: str, name: str) -> Classification | None:
        """Required/preferred as stated by the text around ``evidence``, or ``None`` when it does not say."""

        segment = self.segment_for(evidence)
        if segment is None:
            return None
        if segment.both_cues:
            # "Python required, Go is a plus": decide by the clause that names the item.
            name_key = match_key(name)
            for clause in re.split(r",|\band\b|\bbut\b", segment.text):
                clause_key = match_key(clause)
                if name_key and (name_key in clause_key or skills.mentions(clause_key, name, allow_ambiguous=True)):
                    return _cue(clause)
            return None
        return segment.cue or segment.heading_context


# --------------------------------------------------------------------------- verification


def _name_in_text(job: JobText, name: str) -> bool:
    return job.source.contains(name) or skills.mentions(job.source.key, name, allow_ambiguous=True)


def _verify_requirement(raw: AIRequirement, job: JobText, tally: Tally) -> JobRequirement | None:
    name = clean_value(raw.name)
    category = _category(raw.category)
    if not name or category is None or len(name) > 160:
        tally.drop()
        return None
    if category in ("technical_skill", "soft_skill", "certification") and len(name) > 80:
        tally.drop()
        return None

    evidence = clean_value(raw.evidence)
    if not (evidence and job.source.contains(evidence)):
        evidence = job.sentence_mentioning(name)
    if not evidence:
        tally.drop()
        return None
    if category in ("technical_skill", "certification") and not _name_in_text(job, name):
        # The evidence exists, but this skill is not actually named in the job description.
        tally.drop()
        return None

    importance: Importance = raw.importance.lower() if raw.importance.lower() in _IMPORTANCE else "medium"  # type: ignore[assignment]
    return JobRequirement(
        id="",
        name=name,
        category=category,
        classification="required",
        classification_source="default",
        importance=importance,
        evidence=evidence,
        status="verified",
        min_years=parse_min_years(evidence) if category == "experience" else None,
    )


def _dedupe_key(requirement: JobRequirement) -> tuple[str, str]:
    if requirement.category in ("technical_skill", "soft_skill"):
        return requirement.category, skills.canonical(requirement.name)
    return requirement.category, skills.normalize_term(requirement.name)


def build_structured_job(raw: AIJobExtraction, *, text: str, provider_name: str) -> StructuredJob:
    """Verify model output against ``text`` and assemble the trusted job structure."""

    job = JobText(text)
    tally = Tally()
    reclassified = 0

    info = JobInfo(
        title=verify_text_field(raw.title, job.source, tally, max_chars=160),
        company=verify_text_field(raw.company, job.source, tally, max_chars=120),
        location=verify_text_field(raw.location, job.source, tally, allow_inferred=True, max_chars=120),
        work_arrangement=verify_text_field(raw.work_arrangement, job.source, tally, allow_inferred=True, max_chars=80),
        employment_type=verify_text_field(raw.employment_type, job.source, tally, allow_inferred=True, max_chars=80),
        seniority=verify_text_field(raw.seniority, job.source, tally, allow_inferred=True, max_chars=60),
    )

    requirements: list[JobRequirement] = []
    seen: set[tuple[str, str]] = set()
    for raw_requirement in raw.requirements:
        requirement = _verify_requirement(raw_requirement, job, tally)
        if requirement is None:
            continue
        key = _dedupe_key(requirement)
        if key in seen:
            continue
        seen.add(key)

        ai_class = raw_requirement.classification.strip().lower()
        text_class = job.classify(requirement.evidence, requirement.name)
        source: ClassificationSource
        if text_class is not None:
            classification, source = text_class, "text"
            if ai_class in ("required", "preferred") and ai_class != text_class:
                reclassified += 1
        elif ai_class in ("required", "preferred"):
            classification, source = ai_class, "ai"  # type: ignore[assignment]
        else:
            classification, source = "required", "default"
        requirement.classification = classification
        requirement.classification_source = source
        requirements.append(requirement)

    # Deterministic safety net: well-known skills named in the text that the model missed.
    detected = 0
    known = {skills.canonical(r.name) for r in requirements if r.category == "technical_skill"}
    for entry in skills.scan(job.source.key):
        if skills.normalize_term(entry.canonical) in known:
            continue
        evidence = job.sentence_mentioning(entry.canonical)
        if evidence is None:
            continue
        text_class = job.classify(evidence, entry.canonical)
        requirements.append(
            JobRequirement(
                id="",
                name=entry.canonical,
                category="technical_skill",
                classification=text_class or "preferred",
                classification_source="text" if text_class else "default",
                importance="low",
                evidence=evidence,
                status="detected",
            )
        )
        known.add(skills.normalize_term(entry.canonical))
        detected += 1

    if len(requirements) > MAX_REQUIREMENTS:
        tally.drop(len(requirements) - MAX_REQUIREMENTS)
        requirements = requirements[:MAX_REQUIREMENTS]
    for index, requirement in enumerate(requirements, start=1):
        requirement.id = f"r{index}"
    _group_alternatives(requirements)

    keywords: list[JobKeyword] = []
    seen_terms: set[str] = set()
    for raw_keyword in raw.keywords:
        term = clean_value(raw_keyword.term)
        if not term or len(term) > 60 or not _name_in_text(job, term):
            tally.drop()
            continue
        term_key = skills.canonical(term)
        if term_key in seen_terms:
            continue
        seen_terms.add(term_key)
        evidence = clean_value(raw_keyword.evidence)
        keywords.append(JobKeyword(term=term, evidence=evidence if job.source.contains(evidence) else None))
    for entry in skills.scan(job.source.key):
        term_key = skills.normalize_term(entry.canonical)
        if term_key not in seen_terms:
            seen_terms.add(term_key)
            keywords.append(JobKeyword(term=entry.canonical, evidence=job.sentence_mentioning(entry.canonical)))
    keywords = keywords[:MAX_KEYWORDS]

    extraction = JobExtractionInfo(
        provider=provider_name,
        prompt_version=PROMPT_VERSION_JOB_EXTRACTION,
        removed_items=tally.removed,
        reclassified_items=reclassified,
        detected_items=detected,
    )
    if tally.removed:
        extraction.warnings.append(
            f"{tally.removed} extracted item(s) were discarded because they could not be found in the job description."
        )
    if reclassified:
        extraction.warnings.append(
            f"{reclassified} requirement(s) were re-classified as required/preferred to match the job description's "
            "own wording."
        )
    if not requirements:
        extraction.warnings.append("No verifiable requirements were found in this job description.")
    return StructuredJob(info=info, requirements=requirements, keywords=keywords, extraction=extraction)


def _is_alternative(evidence_key: str, first: str, second: str) -> bool:
    """True when the evidence joins the two skills directly as alternatives: "A or B", "A/B".

    Deliberately conservative: in "Python, FastAPI or Django" only FastAPI/Django are alternatives;
    Python stays a separate requirement.
    """

    for a in skills.surface_forms(first):
        for b in skills.surface_forms(second):
            for x, y in ((a, b), (b, a)):
                pattern = skills.term_pattern(x).pattern + r"\s*(?:\bor\b|/)\s*" + skills.term_pattern(y).pattern
                if re.search(pattern, evidence_key):
                    return True
    return False


def _group_alternatives(requirements: list[JobRequirement]) -> None:
    """Assign ``alternative_group`` to technical skills the text offers as alternatives to each other."""

    candidates = [r for r in requirements if r.category == "technical_skill"]
    parent = {r.id: r.id for r in candidates}

    def root(node: str) -> str:
        while parent[node] != node:
            node = parent[node]
        return node

    for i, first in enumerate(candidates):
        for second in candidates[i + 1 :]:
            if first.evidence != second.evidence or first.classification != second.classification:
                continue
            if _is_alternative(match_key(first.evidence), first.name, second.name):
                parent[root(second.id)] = root(first.id)

    groups: dict[str, list[JobRequirement]] = {}
    for requirement in candidates:
        groups.setdefault(root(requirement.id), []).append(requirement)
    number = 0
    for members in groups.values():
        if len(members) > 1:
            number += 1
            for member in members:
                member.alternative_group = f"g{number}"


def extract_structured_job(provider: AIProvider, *, text: str) -> StructuredJob:
    system, prompt = build_job_extraction_prompt(text)
    try:
        raw_text = provider.generate_json(
            system=system,
            prompt=prompt,
            json_schema=response_schema(AIJobExtraction),
            max_output_tokens=MAX_OUTPUT_TOKENS_JOB_EXTRACTION,
            task="job_extraction",
        )
    except AIProviderError as exc:
        raise AIUpstreamError(str(exc)) from exc

    raw = parse_model_output(
        raw_text,
        AIJobExtraction,
        provider=provider.name,
        task="job_extraction",
        prompt_version=PROMPT_VERSION_JOB_EXTRACTION,
        user_message="The AI provider returned an unexpected job description format.",
    )

    structured = build_structured_job(raw, text=text, provider_name=provider.name)
    logger.info(
        "job_extracted",
        extra={
            "provider": provider.name,
            "requirements": len(structured.requirements),
            "removed_items": structured.extraction.removed_items,
            "detected_items": structured.extraction.detected_items,
        },
    )
    return structured
