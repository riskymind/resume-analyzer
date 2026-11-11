"""Deterministic resume-vs-job matching.

``match_resume_to_job`` is a pure function of:

- the verified structured resume and its text,
- the verified structured job description,
- precomputed semantic signals (embedding similarities, possibly unavailable),
- the matching configuration, and
- an ``as_of`` date (used for "Present" end dates).

The same inputs always produce the same report. No AI call happens here, and
the model never supplies a number. Independent of the resume quality score
(``app.services.scoring``): nothing here reads or changes it.
Methodology: docs/job-matching-methodology.md.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from app.parsing.signals import is_present, parse_date
from app.schemas.job import JobRequirement, StructuredJob
from app.schemas.matching import (
    ComponentKey,
    ComponentScore,
    Confidence,
    ExperienceAnalysis,
    KeywordAnalysis,
    MatchRecommendation,
    MatchRecommendations,
    MatchReport,
    Methodology,
    QualificationsAnalysis,
    RequirementResult,
    ResumeEvidence,
    SemanticInfo,
    SemanticSignals,
    SeniorityAlignment,
    SkillRef,
    SkillsAnalysis,
)
from app.schemas.resume import ExperienceEntry, StructuredResume
from app.services.extraction import match_key
from app.services.job_extraction import parse_min_years
from app.services.matching import skills
from app.services.matching.config import COMPONENT_LABELS, DEFAULT_MATCHING_CONFIG, MatchingConfig

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.]*")
_STOPWORDS = frozenset(
    """
    a an and or the of to in on for with at by from as is are be been being this that these those it its into
    our your you we they their will would should can could may might must shall about across over under within
    using use used via per such other etc e.g i.e including include includes plus also well both any all each
    experience experienced years year yrs ability able strong solid proven good great excellent knowledge
    understanding working work works familiarity familiar proficiency proficient skills skill hands hands-on
    demonstrated track record environment environments required requirement requirements preferred plus bonus
    nice have has having role team teams new related relevant equivalent similar field fields degree
    """.split()
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_YEARS_CLAIM = re.compile(r"\b\d{1,2}(?:\.\d)?\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)

_LEVEL_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (5, re.compile(r"\b(?:ph\.?\s?d|doctorate|doctoral|dphil)\b")),
    (4, re.compile(r"\b(?:master'?s?|msc|m\.sc|mba|meng|m\.eng|mphil|postgraduate degree)\b")),
    (3, re.compile(r"\b(?:bachelor'?s?|bsc|b\.sc|beng|b\.eng|btech|b\.tech|undergraduate degree|four-year degree)\b")),
    (2, re.compile(r"\bassociate'?s? degree\b")),
    (1, re.compile(r"\b(?:high school|secondary school|ged)\b")),
)
_LEVEL_SHORT = ((4, re.compile(r"\b(?:M\.?S\.?|M\.?A\.?)\b")), (3, re.compile(r"\b(?:B\.?S\.?|B\.?A\.?)\b")))
_LEVEL_NAMES = {1: "high school", 2: "associate degree", 3: "bachelor's degree", 4: "master's degree", 5: "doctorate"}
_CERT_VENDORS = frozenset(
    """
    aws amazon azure microsoft google gcp cisco comptia pmi scrum oracle kubernetes cncf isc2 isaca salesforce
    redhat itil togaf
    """.split()
)
_SENIORITY: tuple[tuple[int, str, re.Pattern[str]], ...] = (
    (6, "executive", re.compile(r"\b(?:head of|director|vp|vice president|chief|cto|cio|ceo)\b")),
    (5, "principal", re.compile(r"\b(?:principal|distinguished|architect)\b")),
    (4, "lead / staff", re.compile(r"\b(?:lead|staff|manager)\b")),
    (3, "senior", re.compile(r"\b(?:senior|sr\.?)\b")),
    (2, "mid-level", re.compile(r"\b(?:mid|mid-level|intermediate)\b")),
    (1, "junior / entry", re.compile(r"\b(?:junior|jr\.?|entry[- ]level|graduate|associate)\b")),
    (0, "intern", re.compile(r"\b(?:intern|internship|trainee)\b")),
)


def _tokens(text: str) -> set[str]:
    words = set()
    for raw in _TOKEN.findall(match_key(text)):
        word = raw.strip(".")
        if not word or word in _STOPWORDS or (len(word) < 2 and word not in ("c", "r")):
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.add(word)
    return words


def _quote(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


# --------------------------------------------------------------------------- resume index


@dataclass
class _Unit:
    section: str
    label: str | None
    text: str
    key: str
    tokens: set[str]
    role_index: int | None = None


@dataclass
class _SkillItem:
    name: str
    section: str
    label: str | None
    evidence: str | None
    soft: bool = False
    inferred: bool = False


@dataclass
class _ResumeIndex:
    units: list[_Unit] = field(default_factory=list)
    skill_items: list[_SkillItem] = field(default_factory=list)
    full_key: str = ""
    full_text: str = ""

    def evidence(self, unit: _Unit) -> ResumeEvidence:
        return ResumeEvidence(section=unit.section, label=unit.label, text=_quote(unit.text))


def _role_label(entry: ExperienceEntry) -> str:
    parts = [p.value for p in (entry.title, entry.employer) if p.present and p.value]
    return ", ".join(parts) or "Experience entry"


def _build_index(resume: StructuredResume, text: str) -> _ResumeIndex:
    index = _ResumeIndex(full_key=match_key(text), full_text=text)

    def unit(section: str, label: str | None, content: str | None, role: int | None = None) -> None:
        if content and content.strip():
            index.units.append(_Unit(section, label, content, match_key(content), _tokens(content), role))

    if resume.summary.present:
        unit("summary", "Summary", resume.summary.value)
    for position, entry in enumerate(resume.experience):
        label = _role_label(entry)
        unit("experience", label, entry.title.value if entry.title.present else None, position)
        for bullet in entry.bullets:
            unit("experience", label, bullet.text, position)
    for project in resume.projects:
        project_label = project.name.value if project.name.present and project.name.value else "Project"
        unit("projects", project_label, project.description.value if project.description.present else None)
        for tech in project.technologies:
            index.skill_items.append(_SkillItem(tech, "projects", project_label, None))
    for education in resume.education:
        parts = [f.value for f in (education.qualification, education.field_of_study, education.institution) if f.value]
        unit("education", None, ", ".join(parts))
    for cert in resume.certifications:
        unit("certifications", None, cert.name.value)
    for skill in resume.technical_skills:
        index.skill_items.append(_SkillItem(skill.name, "skills", "Skills", skill.evidence))
    for skill in resume.soft_skills:
        index.skill_items.append(
            _SkillItem(
                skill.name, "skills", "Soft skills", skill.evidence, soft=True, inferred=skill.status == "inferred"
            )
        )
    return index


def _snippet_around(text: str, term: str) -> str:
    for sentence in _SENTENCE.split(text):
        if skills.mentions(match_key(sentence), term):
            return _quote(sentence)
    return _quote(term)


# --------------------------------------------------------------------------- per-requirement evaluation


@dataclass
class _Eval:
    status: str
    match_type: str
    credit: float
    explanation: str
    evidence: list[ResumeEvidence] = field(default_factory=list)
    related_to: str | None = None
    similarity: float | None = None
    candidate_years: float | None = None
    required_years: float | None = None


def _find_exact(index: _ResumeIndex, term: str, *, soft: bool = False) -> tuple[list[ResumeEvidence], bool]:
    """Evidence that the resume names ``term`` (or a true alias). Second value: only via an inferred soft skill."""

    target = skills.canonical(term)
    evidence: list[ResumeEvidence] = []
    inferred_only = False
    for item in index.skill_items:
        if item.soft and not soft:
            continue
        if skills.canonical(item.name) == target or (soft and target in skills.normalize_term(item.name)):
            text = item.evidence if (item.inferred and item.evidence) else item.name
            evidence.append(ResumeEvidence(section=item.section, label=item.label, text=_quote(text)))
            inferred_only = item.inferred
            break
    for unit in index.units:
        if len(evidence) >= 3:
            break
        if skills.mentions(unit.key, term):
            evidence.append(index.evidence(unit))
            inferred_only = False
    if not evidence and skills.mentions(index.full_key, term):
        evidence.append(ResumeEvidence(section="resume text", text=_snippet_around(index.full_text, term)))
    return evidence, inferred_only and len(evidence) == 1


def _resume_skill_names(index: _ResumeIndex) -> list[str]:
    names = [item.name for item in index.skill_items if not item.soft]
    names += [entry.canonical for entry in skills.scan(index.full_key)]
    return list(dict.fromkeys(names))


def _eval_skill(req: JobRequirement, index: _ResumeIndex, signals: SemanticSignals, config: MatchingConfig) -> _Eval:
    soft = req.category == "soft_skill"
    evidence, inferred_only = _find_exact(index, req.name, soft=soft)
    if evidence:
        if soft and inferred_only:
            return _Eval(
                "matched", "evidenced", config.exact_credit,
                f"The resume demonstrates {req.name} in a sentence, though it does not name the skill.", evidence,
            )  # fmt: skip
        return _Eval("matched", "exact", config.exact_credit, f"The resume names {req.name}.", evidence)

    if not soft:
        for name in _resume_skill_names(index):
            if skills.same_family(req.name, name):
                found, _ = _find_exact(index, name)
                return _Eval(
                    "related", "related_lexicon", config.related_credit,
                    f"The job asks for {req.name}; the resume shows {name}, a related but different skill. "
                    f"This is not treated as having {req.name}.",
                    found, related_to=name,
                )  # fmt: skip

    pair = signals.skill_pairs.get(req.id) if signals.status == "available" else None
    if (
        pair
        and pair.similarity >= config.semantic_related_threshold
        and skills.canonical(pair.resume_text) != skills.canonical(req.name)
    ):
        found, _ = _find_exact(index, pair.resume_text, soft=soft)
        return _Eval(
            "related", "related_semantic", config.related_credit,
            f"The job asks for {req.name}; the resume shows {pair.resume_text}, which is semantically similar "
            f"(similarity {pair.similarity:.2f}) but not the same skill.",
            found, related_to=pair.resume_text, similarity=pair.similarity,
        )  # fmt: skip

    return _Eval(
        "missing", "none", 0.0,
        f"No mention of {req.name} was found in the resume's skills, experience, projects or summary. "
        "The candidate may still have it, but the resume does not show it.",
    )  # fmt: skip


@dataclass
class _Years:
    total: float | None
    stated: float | None
    role_spans: dict[int, float]


def _months(start: tuple[int, int], end: tuple[int, int]) -> int:
    return (end[0] - start[0]) * 12 + (end[1] - start[1])


def _role_interval(entry: ExperienceEntry, as_of: date) -> tuple[int, int] | None:
    start = parse_date(entry.start_date.value) if entry.start_date.present else None
    if start is None:
        return None
    if entry.end_date.present and is_present(entry.end_date.value):
        end = (as_of.year, as_of.month)
    else:
        parsed_end = parse_date(entry.end_date.value) if entry.end_date.present else None
        if parsed_end is None:
            return None
        end = parsed_end
    # Year-only dates count from/to January: "2018 - 2021" is three years (a conservative reading).
    start_index = start[0] * 12 + max(start[1], 1) - 1
    end_index = end[0] * 12 + max(end[1], 1) - 1
    return (start_index, end_index) if end_index >= start_index else None


def _merged_years(intervals: Iterable[tuple[int, int]]) -> float:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return round(sum(end - start for start, end in merged) / 12, 1)


def _years_profile(resume: StructuredResume, as_of: date) -> tuple[dict[int, tuple[int, int]], float | None]:
    intervals = {
        position: interval
        for position, entry in enumerate(resume.experience)
        if (interval := _role_interval(entry, as_of)) is not None
    }
    return intervals, (_merged_years(intervals.values()) if intervals else None)


def _stated_years(index: _ResumeIndex, domain: list[str]) -> float | None:
    """Largest number of years the resume itself states, in a sentence mentioning the domain (if any)."""

    best: float | None = None
    for unit in index.units:
        for sentence in _SENTENCE.split(unit.text):
            if not _YEARS_CLAIM.search(sentence):
                continue
            if domain and not any(skills.mentions(match_key(sentence), term) for term in domain):
                continue
            value = parse_min_years(sentence)
            if value is not None and (best is None or value > best):
                best = value
    return best


def _eval_years(
    req: JobRequirement,
    resume: StructuredResume,
    index: _ResumeIndex,
    intervals: dict[int, tuple[int, int]],
    total_years: float | None,
    config: MatchingConfig,
) -> _Eval:
    required = req.min_years
    assert required is not None
    domain = [entry.canonical for entry in skills.scan(match_key(req.name))]

    if domain:
        relevant_roles = {
            unit.role_index
            for unit in index.units
            if unit.role_index is not None and any(skills.mentions(unit.key, term) for term in domain)
        }
        dated = _merged_years(intervals[r] for r in relevant_roles if r in intervals) if relevant_roles else 0.0
        stated = _stated_years(index, domain) or 0.0
        candidate = max(dated, stated)
        evidence = [
            ResumeEvidence(section="experience", label=_role_label(resume.experience[r]), text=_role_dates(resume, r))
            for r in sorted(relevant_roles)
        ][:4]
        basis = f"roles mentioning {', '.join(domain)}"
    else:
        stated = _stated_years(index, []) or 0.0
        candidate = max(total_years or 0.0, stated)
        evidence = [
            ResumeEvidence(section="experience", label=_role_label(resume.experience[r]), text=_role_dates(resume, r))
            for r in sorted(intervals)
        ][:4]
        basis = "all dated roles"
    if stated and stated >= candidate:
        evidence.insert(0, ResumeEvidence(section="summary", label="Stated in resume", text=f"{stated:g} years"))

    if candidate >= required:
        return _Eval(
            "matched", "years", config.exact_credit,
            f"The job asks for {required:g}+ years; the resume evidences about {candidate:g} years ({basis}).",
            evidence, candidate_years=candidate, required_years=required,
        )  # fmt: skip
    if candidate > 0:
        return _Eval(
            "partial", "years", round(min(1.0, candidate / required), 4),
            f"The job asks for {required:g}+ years; the resume evidences about {candidate:g} years ({basis}). "
            "If you have more relevant experience, make the dates and technologies explicit.",
            evidence, candidate_years=candidate, required_years=required,
        )  # fmt: skip
    if domain and any(_find_exact(index, term)[0] for term in domain):
        found = [e for term in domain for e in _find_exact(index, term)[0]][:2]
        return _Eval(
            "partial", "years", config.years_unverified_credit,
            f"The resume mentions {', '.join(domain)} but no dated role shows how long it was used, so the "
            f"{required:g}+ years requirement cannot be verified.",
            found, candidate_years=None, required_years=required,
        )  # fmt: skip
    reason = "no dated roles were found" if not intervals else f"no dated role mentions {', '.join(domain)}"
    return _Eval(
        "missing", "years", 0.0,
        f"The job asks for {required:g}+ years, but {reason}, so the resume does not evidence this experience.",
        required_years=required,
    )  # fmt: skip


def _role_dates(resume: StructuredResume, position: int) -> str:
    entry = resume.experience[position]
    start = entry.start_date.value or "?"
    end = entry.end_date.value or "?"
    return f"{start} \u2013 {end}"


def _eval_text(req: JobRequirement, index: _ResumeIndex, signals: SemanticSignals, config: MatchingConfig) -> _Eval:
    """Experience descriptions and responsibilities: wording overlap, then semantic similarity."""

    wanted = _tokens(req.name) | (_tokens(req.evidence) if len(_tokens(req.name)) < 2 else set())
    best_unit: _Unit | None = None
    best = 0.0
    if wanted:
        for unit in index.units:
            if unit.section not in ("experience", "summary", "projects"):
                continue
            overlap = len(wanted & unit.tokens) / len(wanted)
            if overlap > best + 1e-9:
                best, best_unit = overlap, unit
    best = round(best, 4)

    if best_unit is not None and best >= config.text_overlap_full:
        return _Eval(
            "matched", "text_overlap", config.exact_credit,
            "A resume entry describes closely matching work.", [index.evidence(best_unit)],
        )  # fmt: skip
    pair = signals.text_pairs.get(req.id) if signals.status == "available" else None
    if pair and pair.similarity >= config.semantic_text_threshold:
        similar = next((u for u in index.units if u.text == pair.resume_text), None)
        fallback = ResumeEvidence(section="experience", text=_quote(pair.resume_text))
        return _Eval(
            "partial", "semantic_text", config.semantic_text_credit,
            f"A resume entry describes similar work (similarity {pair.similarity:.2f}); consider using wording "
            "closer to the job description where it is accurate.",
            [index.evidence(similar) if similar else fallback],
            similarity=pair.similarity,
        )  # fmt: skip
    if best_unit is not None and best >= config.text_overlap_partial:
        return _Eval(
            "partial", "text_overlap", config.text_partial_credit,
            "A resume entry partly overlaps with this requirement; it may be worth describing that work more fully.",
            [index.evidence(best_unit)],
        )  # fmt: skip
    return _Eval(
        "missing", "none", 0.0,
        "No resume entry describes this kind of work. If you have done it, add a specific bullet describing it.",
    )  # fmt: skip


def _levels(text: str) -> list[int]:
    key = match_key(text)
    found = [level for level, pattern in _LEVEL_PATTERNS if pattern.search(key)]
    found += [level for level, pattern in _LEVEL_SHORT if pattern.search(text)]
    return found


def _field_tokens(evidence: str) -> set[str]:
    match = re.search(r"\bin\s+(.+?)(?:\bor\b\s+(?:a\s+)?(?:related|equivalent|similar)|[.;(]|$)", evidence, re.I)
    if not match:
        return set()
    return _tokens(match.group(1)) - {"bachelor", "master", "phd", "bsc", "msc", "level", "university"}


def _eval_education(req: JobRequirement, resume: StructuredResume, config: MatchingConfig) -> _Eval:
    text = f"{req.name}. {req.evidence}"
    required_levels = _levels(text)
    required_level = min(required_levels) if required_levels else None
    wanted_field = _field_tokens(req.evidence) or _field_tokens(req.name)
    accepts_related = bool(re.search(r"\b(?:related|equivalent|similar)\b", text, re.I))

    if not resume.education:
        return _Eval(
            "missing", "education", 0.0, "The resume lists no education, so this requirement is not evidenced."
        )

    best: _Eval | None = None
    for entry in resume.education:
        description = ", ".join(
            f.value for f in (entry.qualification, entry.field_of_study, entry.institution) if f.present and f.value
        )
        levels = _levels(" ".join(f.value or "" for f in (entry.qualification, entry.field_of_study)))
        level = max(levels) if levels else None
        evidence = [ResumeEvidence(section="education", text=_quote(description))]
        field_tokens = _tokens(" ".join(f.value or "" for f in (entry.field_of_study, entry.qualification)))
        field_ok = not wanted_field or bool(wanted_field & field_tokens)

        if required_level is not None and level is not None and level < required_level:
            candidate = _Eval(
                "partial", "education", config.education_level_below_credit,
                f"The job asks for a {_LEVEL_NAMES[required_level]}; the resume shows {description}, a lower level.",
                evidence,
            )  # fmt: skip
        elif required_level is not None and level is None:
            candidate = _Eval(
                "partial", "education", config.education_field_mismatch_credit,
                f"The resume lists {description}, but its degree level could not be determined.", evidence,
            )  # fmt: skip
        elif field_ok:
            candidate = _Eval("matched", "education", config.exact_credit, f"The resume shows {description}.", evidence)
        else:
            note = " The job accepts related fields; explain how yours relates." if accepts_related else ""
            candidate = _Eval(
                "partial", "education", config.education_field_mismatch_credit,
                f"The degree level meets the requirement, but the field ({description}) differs from the one asked "
                f"for.{note}",
                evidence,
            )  # fmt: skip
        if best is None or candidate.credit > best.credit:
            best = candidate
    assert best is not None
    return best


def _eval_certification(
    req: JobRequirement, resume: StructuredResume, index: _ResumeIndex, config: MatchingConfig
) -> _Eval:
    wanted = _tokens(req.name)
    for cert in resume.certifications:
        name = cert.name.value or ""
        have = _tokens(name)
        if wanted and have and (len(wanted & have) / len(wanted) >= 0.8 or len(wanted & have) / len(have) >= 0.8):
            return _Eval(
                "matched", "exact", config.exact_credit, f"The resume lists the certification {name}.",
                [ResumeEvidence(section="certifications", text=_quote(name))],
            )  # fmt: skip
    if len(match_key(req.name)) >= 4 and match_key(req.name) in index.full_key:
        return _Eval(
            "matched", "exact", config.exact_credit, f"The resume mentions {req.name}.",
            [ResumeEvidence(section="resume text", text=_quote(req.name))],
        )  # fmt: skip
    vendors = wanted & _CERT_VENDORS
    for cert in resume.certifications:
        name = cert.name.value or ""
        if vendors & _tokens(name):
            return _Eval(
                "related", "related_lexicon", config.related_credit,
                f"The resume lists {name}, a related certification from the same vendor, not {req.name}.",
                [ResumeEvidence(section="certifications", text=_quote(name))], related_to=name,
            )  # fmt: skip
    return _Eval(
        "missing", "none", 0.0,
        f"The resume does not list {req.name}. If you hold it, add it to a certifications section.",
    )  # fmt: skip


# --------------------------------------------------------------------------- assembly


def _component(req: JobRequirement) -> ComponentKey:
    if req.category == "responsibility":
        return "responsibilities"
    if req.classification == "preferred":
        return "preferred_qualifications"
    return {
        "technical_skill": "required_skills",
        "soft_skill": "required_skills",
        "experience": "experience",
        "education": "education",
        "certification": "certifications",
    }[req.category]  # type: ignore[return-value]


def _seniority(text: str | None) -> tuple[int, str] | None:
    if not text:
        return None
    key = match_key(text)
    for rank, name, pattern in _SENIORITY:
        if pattern.search(key):
            return rank, name
    return None


def _seniority_alignment(resume: StructuredResume, job: StructuredJob) -> SeniorityAlignment:
    job_text = job.info.seniority.value if job.info.seniority.present else job.info.title.value
    job_level = _seniority(job_text)
    resume_level = None
    for entry in resume.experience:  # resumes list the most recent role first
        if entry.title.present:
            resume_level = _seniority(entry.title.value)
            break
    if job_level is None or resume_level is None:
        missing = "job" if job_level is None else "most recent resume role"
        return SeniorityAlignment(
            job_level=job_level[1] if job_level else None,
            resume_level=resume_level[1] if resume_level else None,
            status="unknown",
            explanation=f"The {missing} title does not state a seniority level, so it was not compared.",
        )
    if job_level[0] == resume_level[0]:
        status, text = "aligned", "The most recent role's level matches the job's level."
    elif resume_level[0] < job_level[0]:
        status, text = "below", "The most recent role is at a lower level than the job; highlight scope and ownership."
    else:
        status, text = "above", "The most recent role is at a higher level than the job."
    return SeniorityAlignment(job_level=job_level[1], resume_level=resume_level[1], status=status, explanation=text)


def _apply_alternatives(results: list[RequirementResult], groups: dict[str, str | None]) -> None:
    """Score each group of alternatives ("FastAPI or Django") once, by its best-evidenced member."""

    by_group: dict[str, list[RequirementResult]] = {}
    for result in results:
        group = groups.get(result.requirement_id)
        result.alternative_group = group
        if group:
            by_group.setdefault(group, []).append(result)
    for members in by_group.values():
        best = max(members, key=lambda r: (r.credit, -members.index(r)))
        alternatives = " or ".join(m.name for m in members)
        for member in members:
            if member is best:
                continue
            member.counted = False
            member.satisfied_by_alternative = best.name
            member.explanation += (
                f" Not scored separately: the job accepts {alternatives}, and this group is scored by {best.name}."
            )


def _round_half_up(value: float) -> int:
    return math.floor(round(value, 6) + 0.5)


def match_resume_to_job(
    resume: StructuredResume,
    resume_text: str,
    job: StructuredJob,
    signals: SemanticSignals,
    *,
    as_of: date,
    config: MatchingConfig = DEFAULT_MATCHING_CONFIG,
) -> MatchReport:
    index = _build_index(resume, resume_text)
    intervals, total_years = _years_profile(resume, as_of)

    results: list[RequirementResult] = []
    for req in job.requirements:
        if req.category in ("technical_skill", "soft_skill"):
            ev = _eval_skill(req, index, signals, config)
        elif req.category == "experience" and req.min_years is not None:
            ev = _eval_years(req, resume, index, intervals, total_years, config)
        elif req.category in ("experience", "responsibility"):
            ev = _eval_text(req, index, signals, config)
        elif req.category == "education":
            ev = _eval_education(req, resume, config)
        else:
            ev = _eval_certification(req, resume, index, config)
        results.append(
            RequirementResult(
                requirement_id=req.id,
                name=req.name,
                category=req.category,
                classification=req.classification,
                importance=req.importance,
                jd_evidence=req.evidence,
                status=ev.status,
                match_type=ev.match_type,
                credit=ev.credit,
                weight=config.importance_weights[req.importance],
                component=_component(req),
                evidence=ev.evidence,
                related_to=ev.related_to,
                similarity=ev.similarity,
                candidate_years=ev.candidate_years,
                required_years=ev.required_years,
                explanation=ev.explanation,
            )
        )

    _apply_alternatives(results, {r.id: r.alternative_group for r in job.requirements})
    excluded_terms = {skills.canonical(r.name) for r in results if not r.counted}

    # Keywords
    present_keywords: list[str] = []
    missing_keywords: list[str] = []
    keyword_terms = [k for k in job.keywords if skills.canonical(k.term) not in excluded_terms]
    for keyword in keyword_terms:
        if skills.mentions(index.full_key, keyword.term) or (
            len(match_key(keyword.term)) >= 4 and match_key(keyword.term) in index.full_key
        ):
            present_keywords.append(keyword.term)
        else:
            missing_keywords.append(keyword.term)

    # Component scores
    raw_scores: dict[ComponentKey, float | None] = {}
    members: dict[ComponentKey, list[RequirementResult]] = {key: [] for key in config.weights}
    for result in results:
        if result.counted:
            members[result.component].append(result)
    for key in config.weights:
        if key == "keywords":
            total = len(keyword_terms)
            raw_scores[key] = (len(present_keywords) / total * 100) if total else None
            continue
        items = members[key]
        weight_sum = sum(r.weight for r in items)
        raw_scores[key] = (sum(r.credit * r.weight for r in items) / weight_sum * 100) if weight_sum else None

    applicable = {k: w for k, w in config.weights.items() if raw_scores[k] is not None and w > 0}
    weight_total = sum(applicable.values())
    components: list[ComponentScore] = []
    raw_total = 0.0
    effective: dict[ComponentKey, float] = {}
    for key, weight in config.weights.items():
        score = raw_scores[key]
        eff = (weight / weight_total * 100) if (key in applicable and weight_total) else 0.0
        effective[key] = eff
        contribution = eff * (score or 0.0) / 100
        raw_total += contribution
        components.append(
            ComponentScore(
                key=key,
                label=COMPONENT_LABELS[key],
                weight=weight,
                effective_weight=round(eff, 2),
                score=None if score is None else _round_half_up(score),
                contribution=round(contribution, 2),
                requirement_ids=[r.requirement_id for r in members[key]],
            )
        )

    warnings = list(job.extraction.warnings[-1:]) if not job.requirements else []
    score = _round_half_up(raw_total) if weight_total else 0
    if not job.requirements and not job.keywords:
        warnings.append(
            "The job description contained no verifiable requirements or keywords, so no match is possible."
        )

    mandatory = [r for r in results if r.counted and r.classification == "required" and r.category != "responsibility"]
    missing_mandatory = [r for r in mandatory if r.status == "missing"]
    score_cap: str | None = None
    if mandatory and len(missing_mandatory) / len(mandatory) > 0.5 and score > config.majority_required_missing_cap:
        score = config.majority_required_missing_cap
        score_cap = f"Capped at {score}: the resume shows no evidence for more than half of the mandatory requirements."
    elif missing_mandatory and score > config.missing_required_cap:
        score = config.missing_required_cap
        score_cap = (
            f"Capped at {score}: {len(missing_mandatory)} mandatory requirement(s) have no evidence in the resume."
        )

    # Analyses
    def ref(r: RequirementResult) -> SkillRef:
        return SkillRef(
            requirement_id=r.requirement_id, name=r.name, classification=r.classification, category=r.category,
            resume_term=r.related_to,
        )  # fmt: skip

    skill_results = [r for r in results if r.category in ("technical_skill", "soft_skill")]
    skills_analysis = SkillsAnalysis(
        exact=[ref(r) for r in skill_results if r.status == "matched"],
        related=[ref(r) for r in skill_results if r.status == "related"],
        missing=[ref(r) for r in skill_results if r.status == "missing" and r.counted],
        required_total=sum(1 for r in skill_results if r.classification == "required"),
        preferred_total=sum(1 for r in skill_results if r.classification == "preferred"),
    )

    experience_results = [r for r in results if r.category == "experience"]
    year_requirements = [
        r.required_years for r in experience_results if r.required_years and r.classification == "required"
    ]
    relevant_roles = list(
        dict.fromkeys(
            e.label
            for r in results
            if r.status != "missing"
            for e in r.evidence
            if e.section == "experience" and e.label
        )
    )
    experience_analysis = ExperienceAnalysis(
        candidate_years=total_years,
        stated_years=_stated_years(index, []),
        required_years=max(year_requirements) if year_requirements else None,
        relevant_roles=relevant_roles[:8],
        gaps=[f"{r.name}: {r.explanation}" for r in experience_results if r.status != "matched"],
        responsibility_alignment=next(c.score for c in components if c.key == "responsibilities"),
        seniority=_seniority_alignment(resume, job),
    )

    qualifications = QualificationsAnalysis(
        education_matched=[ref(r) for r in results if r.category == "education" and r.status == "matched"],
        education_missing=[ref(r) for r in results if r.category == "education" and r.status != "matched"],
        certifications_matched=[ref(r) for r in results if r.category == "certification" and r.status == "matched"],
        certifications_missing=[ref(r) for r in results if r.category == "certification" and r.status != "matched"],
    )

    keyword_analysis = KeywordAnalysis(
        present=present_keywords,
        missing=missing_keywords,
        coverage=_round_half_up(raw_scores["keywords"]) if raw_scores["keywords"] is not None else None,
    )

    recommendations = _recommendations(
        [r for r in results if r.counted], members, effective, missing_keywords, len(keyword_terms)
    )

    # Confidence
    assessed = [r for r in results if r.counted]
    with_evidence = [r for r in assessed if r.status != "missing"]
    coverage = _round_half_up(len(with_evidence) / len(assessed) * 100) if assessed else 0
    reasons: list[str] = []
    level = "high"
    if len([r for r in results if r.category != "responsibility"]) < 3:
        level = "low"
        reasons.append("Fewer than three requirements could be verified in the job description.")
    if signals.status != "available":
        level = "medium" if level == "high" else level
        reasons.append(
            "Semantic matching was "
            + ("disabled" if signals.status == "disabled" else "unavailable")
            + "; related skills were identified only from the built-in skill families."
        )
    if any(r.required_years for r in experience_results) and not intervals:
        level = "medium" if level == "high" else level
        reasons.append("The resume's roles have no parseable dates, so years of experience could not be measured.")
    if not reasons:
        reasons.append("Requirements were verified in the job description and compared with structured resume data.")

    weights_text = " + ".join(f"{w}\u00b7{k}" for k, w in config.weights.items())
    methodology = Methodology(
        version=config.version,
        formula=(
            f"match = \u03a3 effective_weight \u00d7 component_score / 100, with weights {weights_text}; components "
            "with no requirements are dropped and the remaining weights re-normalised to 100. Each component score is "
            "the importance-weighted average of requirement credits."
        ),
        weights={k: int(v) for k, v in config.weights.items()},
        credits={
            "exact": config.exact_credit,
            "related": config.related_credit,
            "years_unverified": config.years_unverified_credit,
            "text_partial": config.text_partial_credit,
            "semantic_text": config.semantic_text_credit,
            "education_field_mismatch": config.education_field_mismatch_credit,
            "education_level_below": config.education_level_below_credit,
        },
        thresholds={
            "semantic_related": config.semantic_related_threshold,
            "semantic_text": config.semantic_text_threshold,
            "text_overlap_full": config.text_overlap_full,
            "text_overlap_partial": config.text_overlap_partial,
            "missing_required_cap": config.missing_required_cap,
            "majority_required_missing_cap": config.majority_required_missing_cap,
        },
        notes=[
            "Scores are calculated by application code from verified requirements and resume evidence; the AI "
            "never supplies a number.",
            "Related skills earn partial credit and are never treated as the requested skill.",
            "Preferred qualifications are scored in their own component and cannot outweigh required ones.",
        ],
    )

    return MatchReport(
        matching_version=config.version,
        match_score=score,
        label=config.label_for(score),
        classification=config.classification_for(score),
        score_cap=score_cap,
        components=components,
        requirements=results,
        skills=skills_analysis,
        experience=experience_analysis,
        qualifications=qualifications,
        keywords=keyword_analysis,
        recommendations=recommendations,
        semantic=SemanticInfo(
            status=signals.status,
            model=signals.model,
            reason=signals.reason,
            related_threshold=config.semantic_related_threshold,
            text_threshold=config.semantic_text_threshold,
        ),
        confidence=Confidence(level=level, evidence_coverage=coverage, reasons=reasons),
        methodology=methodology,
        warnings=warnings,
    )


def _recommendations(
    results: list[RequirementResult],
    members: dict[ComponentKey, list[RequirementResult]],
    effective: dict[ComponentKey, float],
    missing_keywords: list[str],
    keyword_total: int,
) -> MatchRecommendations:
    items: list[MatchRecommendation] = []
    develop: list[str] = []
    present_better: list[str] = []
    missing_evidence: list[str] = []

    for r in results:
        if r.credit >= 1:
            continue
        weight_sum = sum(m.weight for m in members[r.component]) or 1.0
        impact = round(effective[r.component] * r.weight / weight_sum * (1 - r.credit), 1)
        quote = _quote(r.jd_evidence, 120)
        label = "mandatory" if r.classification == "required" else "preferred"
        if r.status == "missing" and r.category in ("technical_skill", "certification"):
            message = (
                f"The job lists {r.name} as {label} (\u201c{quote}\u201d), but the resume does not mention it. If you "
                "have used it, add it with a concrete example; if not, it is a genuine gap to develop rather "
                "than claim."
            )
            items.append(
                MatchRecommendation(
                    kind="provide_evidence", requirement_id=r.requirement_id, message=message, impact=impact
                )
            )
            missing_evidence.append(r.name)
            develop.append(r.name)
        elif r.status == "missing":
            message = (
                f"Not evidenced: {r.name} (\u201c{quote}\u201d). If your experience covers this, describe it in a "
                "specific bullet."
            )
            kind = "clarify_experience" if r.category in ("experience", "education") else "provide_evidence"
            items.append(
                MatchRecommendation(kind=kind, requirement_id=r.requirement_id, message=message, impact=impact)
            )
            missing_evidence.append(r.name)
        elif r.status == "related":
            message = (
                f"The job asks for {r.name}; your resume shows {r.related_to}. Highlight the transferable work, and "
                f"add {r.name} only if you have actually used it."
            )
            items.append(
                MatchRecommendation(
                    kind="present_better", requirement_id=r.requirement_id, message=message, impact=impact
                )
            )
            present_better.append(f"{r.name} (related: {r.related_to})")
            if r.category == "technical_skill":
                develop.append(r.name)
        else:  # partial
            kind = "clarify_experience" if r.category in ("experience", "education") else "present_better"
            items.append(
                MatchRecommendation(
                    kind=kind, requirement_id=r.requirement_id, message=f"{r.name}: {r.explanation}", impact=impact
                )
            )
            present_better.append(r.name)

    if missing_keywords:
        impact = round(effective["keywords"] * len(missing_keywords) / max(keyword_total, 1), 1)
        items.append(
            MatchRecommendation(
                kind="keyword",
                requirement_id=None,
                message=(
                    "Where they truthfully apply, use the job's own terms: " + ", ".join(missing_keywords[:10]) + "."
                ),
                impact=impact,
            )
        )

    items.sort(key=lambda item: (-item.impact, item.requirement_id or "~"))
    return MatchRecommendations(
        top=items[:8],
        skills_to_develop=list(dict.fromkeys(develop))[:10],
        present_better=list(dict.fromkeys(present_better))[:10],
        missing_evidence=list(dict.fromkeys(missing_evidence))[:12],
    )
