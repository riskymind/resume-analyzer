"""Factual verification of rewritten resume content. Deterministic; no AI involved.

The model only proposes wording. Before any proposal can reach the document,
and again whenever the user saves, every rewritten unit is compared with its
*evidence*: the original bullets it cites (``source_ids``) for experience
bullets, the original description for a project, and the whole original
resume for the summary. Each finding is a :class:`VerificationIssue`:

- ``blocking``: a factual claim the evidence does not support, such as a new
  number, a changed figure, a skill or qualification the resume never
  mentions, the target employer's name, or a role escalated to "led". An AI
  suggestion with a blocking issue is rejected and cannot be applied.
- ``warning``: wording that may change meaning (unverified names, scope
  words, substantially new content). The suggestion waits for the user's review.
- ``info``: neutral notes, for example an entry removed by the user.

Manual edits are checked with the same rules and tagged ``origin = "user"``.
They are kept, since the user is the authority on their own history, but they
are shown as unverified.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.schemas.job import StructuredJob
from app.schemas.rewrite import (
    DocEducation,
    DocExperience,
    Origin,
    ResumeDocument,
    Suggestion,
    VerificationIssue,
    VerificationSummary,
)
from app.services.extraction import match_key
from app.services.matching import skills as lexicon
from app.services.rewriting.document import render_text
from app.services.scoring.lexicon import ACTION_VERBS

CHECKS_APPLIED = [
    "Every number, percentage, amount and year must appear in the original text it rewrites, with the same unit "
    "and scale.",
    "Years-of-experience claims must be stated in the original resume.",
    "Tools, technologies, skills, certifications and degrees must be mentioned in the original resume.",
    "The target employer's name and the target job title cannot be claimed.",
    "Leadership or management cannot be added where the original does not describe it.",
    "Implied scale ('dozens', 'millions', 'a decade') cannot be added.",
    "Employers, job titles, dates, institutions, qualifications and certifications are copied from the original; "
    "manual changes to them are flagged.",
    "Relevant coursework you add must be mentioned in the original resume.",
    "New names, scope words and substantially new content are flagged for review.",
]

# --------------------------------------------------------------------------- numbers

_SPELLED = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "dozen": 12,
}  # fmt: skip
_SPELLED_RE = "|".join(_SPELLED)
_MAGNITUDES = {
    "k": "k", "thousand": "k", "m": "m", "mm": "m", "million": "m", "mn": "m", "b": "b", "bn": "b", "billion": "b",
}  # fmt: skip
_NUMBER = re.compile(
    r"(?<![\w.])(?P<cur>[$€£¥₦₹])?\s?"
    rf"(?P<num>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?|(?<![\w-])(?:{_SPELLED_RE})(?![\w-]))"
    r"(?P<plus>\+)?"
    r"(?:\s?(?P<pct>%|percent\b|per\s?cent\b))?"
    r"(?:\s?(?P<mag>k|mm|m|mn|bn|b|thousand|million|billion)(?![a-z]))?",
)
_YEARS_CLAIM = re.compile(rf"(?<![\w.])(?P<num>\d+(?:\.\d+)?|{_SPELLED_RE})\s*\+?\s*(?:years?|yrs?)(?![a-z])")


@dataclass(frozen=True)
class _Number:
    raw: str
    value: str
    percent: bool
    magnitude: str | None
    currency: bool


def _number_value(token: str) -> str:
    if token in _SPELLED:
        return str(_SPELLED[token])
    numeric = float(token.replace(",", ""))
    return str(int(numeric)) if numeric.is_integer() else repr(numeric)


def _numbers(text_key: str) -> list[_Number]:
    found = []
    for match in _NUMBER.finditer(text_key):
        found.append(
            _Number(
                raw=match.group(0).strip(),
                value=_number_value(match.group("num")),
                percent=bool(match.group("pct")),
                magnitude=_MAGNITUDES.get(match.group("mag") or ""),
                currency=bool(match.group("cur")),
            )
        )
    return found


def _years_claims(text_key: str) -> set[str]:
    return {_number_value(match.group("num")) for match in _YEARS_CLAIM.finditer(text_key)}


# --------------------------------------------------------------------------- vocabularies

_QUALIFICATION = re.compile(
    r"(?<![a-z])(ph\.?\s?d|doctorate|master'?s|masters|mba|m\.\s?sc|msc|b\.\s?sc|bsc|bachelor'?s?|b\.\s?eng|"
    r"beng|m\.\s?eng|meng|associate'?s degree|diploma|certified|certification|certificate|licensed|chartered|"
    r"accredited)(?![a-z])"
)
_QUALIFICATION_GROUPS = {
    "certified": "cert", "certification": "cert", "certificate": "cert",
    "master's": "masters", "masters": "masters", "bachelor": "bachelor", "bachelors": "bachelor",
    "bachelor's": "bachelor", "phd": "phd", "ph.d": "phd", "ph. d": "phd", "doctorate": "phd",
}  # fmt: skip
_CERT_PHRASE = re.compile(
    r"((?:[A-Z][\w+.-]*\s){1,4}Certified(?:\s[A-Z][\w+.-]*){0,4}|Certified(?:\s[A-Z][\w+.-]*){1,4})"
)
_LEADERSHIP = re.compile(
    r"(?<![a-z])(led|leading|lead|leads|managed|manages|managing|manager|mentored|mentoring|mentor|supervised|"
    r"supervising|oversaw|oversee|overseeing|directed|headed|spearheaded|chaired|owned|ownership|"
    r"head of|director)(?![a-z])(?!\s+to\b)"
)
_SCOPE_WORDS = ("company-wide", "organization-wide", "organisation-wide", "enterprise-wide", "globally", "worldwide")
_VAGUE_QUANTITIES = ("decade", "decades", "dozens", "hundreds", "thousands", "millions", "billions", "countless")
_SUPERLATIVES = (
    "award-winning", "award winning", "world-class", "world class", "industry-leading", "best-in-class",
    "top-performing", "top performer", "record-breaking", "renowned", "expert", "unparalleled", "#1", "number one",
)  # fmt: skip
_ORG_SUFFIX = (
    r"(?:Inc|Corp|Corporation|LLC|Ltd|Limited|GmbH|PLC|University|College|Institute|Bank|Group|Labs|"
    r"Technologies|Systems|Foundation|Agency|Ministry|Hospital)\.?"
)
_ORG_WITH_SUFFIX = re.compile(rf"\b((?:[A-Z][\w&'.-]*\s){{1,4}}{_ORG_SUFFIX})(?![\w])")
_ORG_AFTER_VERB = re.compile(r"\b(?:at|joined|employed by)\s+((?:[A-Z][\w&'.-]*)(?:\s+[A-Z][\w&'.-]*){0,3})")
_CAPITALISED = re.compile(r"(?<![\w'])([A-Z][A-Za-z0-9&+.#-]*[A-Za-z0-9+#])")
_WORD = re.compile(r"[a-z][a-z'-]+")

STOPWORDS = frozenset(
    """
    a an and are as at be been being but by for from had has have in into is it its of on or that the their
    this to was were which while who with within without across over under via per than then them they these
    those also more most such using used use through each other both all any some our your my we i me
    """.split()
)
# Generic resume vocabulary: rephrasing with these words is stylistic, not a new claim.
_GENERIC = frozenset(
    """
    team teams work worked working responsible responsibilities ensure ensuring ensured various multiple several
    project projects process processes system systems solution solutions service services application applications
    product products feature features performance quality reliability reliable scalable scalability efficient
    efficiency effective effectively robust high large small complex critical key core new existing internal
    external business stakeholders customer customers client clients user users end-to-end production support
    deliver delivery delivering development develop engineering engineer infrastructure platform platforms data
    requirements operations operational improve improving improvement improvements reduce reducing reduction
    increase increasing time cost costs results result impact outcomes goals daily ongoing successful successfully
    strong proven including include includes related relevant best practices practice standards technical
    cross-functional collaboration collaborate collaborated collaborating partner partners
    """.split()
)


def _stem(word: str) -> str:
    for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ied", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _content_stems(text_key: str) -> set[str]:
    return {
        _stem(word)
        for word in _WORD.findall(text_key)
        if len(word) >= 4 and word not in STOPWORDS and word not in ACTION_VERBS and word not in _GENERIC
    }


_AMBIGUOUS_NAMES = tuple(entry.canonical for entry in lexicon.SKILLS if entry.ambiguous)


def ambiguous_mentions(text: str) -> set[str]:
    """Ambiguous technology names ("Go", "R", "REST") written as names: case-sensitive, not sentence-initial.

    Free-text matching ignores these ("ready to go" is not Go), so they are detected
    from their capitalised form instead.
    """

    found: set[str] = set()
    for name in _AMBIGUOUS_NAMES:
        for match in re.finditer(rf"(?<![\w+#.]){re.escape(name)}(?![\w+#&])", text):
            before = text[: match.start()].rstrip()
            if before and before[-1] not in ".!?:;\n":
                found.add(name)
                break
    return found


def _contains(text_key: str, phrase: str) -> bool:
    needle = match_key(phrase)
    if len(needle) < 2:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", text_key) is not None


# --------------------------------------------------------------------------- context


@dataclass
class VerificationContext:
    """Everything the checks compare against: the original resume and (optionally) the target job."""

    original: ResumeDocument
    resume_text: str
    job: StructuredJob | None = None
    resume_key: str = ""
    document_key: str = ""
    known_skills: set[str] = field(default_factory=set)
    soft_skills: set[str] = field(default_factory=set)
    resume_words: set[str] = field(default_factory=set)
    qualification_groups: set[str] = field(default_factory=set)
    ambiguous_in_resume: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.document_key = match_key(render_text(self.original))
        self.resume_key = match_key(self.resume_text + "\n" + render_text(self.original))
        self.known_skills = {
            lexicon.canonical(name)
            for name in [*self.original.technical_skills, *(t for p in self.original.projects for t in p.technologies)]
        }
        self.soft_skills = {lexicon.canonical(name) for name in self.original.soft_skills}
        self.resume_words = set(re.findall(r"[a-z0-9][a-z0-9&+.#-]*", self.resume_key))
        self.qualification_groups = {_qualification_group(m.group(1)) for m in _QUALIFICATION.finditer(self.resume_key)}
        self.ambiguous_in_resume = ambiguous_mentions(self.resume_text + "\n" + render_text(self.original))

    def mentions_skill(self, term: str) -> bool:
        entry = lexicon.lookup(term)
        if entry is not None and entry.ambiguous and entry.canonical in self.ambiguous_in_resume:
            return True
        return (
            lexicon.canonical(term) in self.known_skills
            or lexicon.canonical(term) in self.soft_skills
            # Ambiguous names ("Go", "R") count only from explicit skill lists, never from free text.
            or lexicon.mentions(self.resume_key, term)
        )


def _qualification_group(term: str) -> str:
    compact = term.replace(" ", "")
    return _QUALIFICATION_GROUPS.get(term, _QUALIFICATION_GROUPS.get(compact, compact.replace(".", "")))


# --------------------------------------------------------------------------- unit checks


@dataclass
class UnitEvidence:
    """What one unit of rewritten text may draw on."""

    key: str  # comparison form of the unit's own source text
    where: str  # human description, e.g. "the original bullet"
    kind: str  # summary | bullet | project | skills


def _issue(code: str, severity: str, message: str, *, term: str | None = None) -> VerificationIssue:
    return VerificationIssue(code=code, severity=severity, message=message, term=term)


def _check_numbers(key: str, evidence: UnitEvidence) -> list[VerificationIssue]:
    issues: list[VerificationIssue] = []
    available = _numbers(evidence.key)
    for number in _numbers(key):
        candidates = [item for item in available if item.value == number.value]
        if not candidates:
            issues.append(
                _issue(
                    "unsupported_number",
                    "blocking",
                    f"“{number.raw}” does not appear in {evidence.where}. Numbers and metrics cannot be added.",
                    term=number.raw,
                )
            )
            continue
        if number.percent and not any(item.percent for item in candidates):
            problem = "is a percentage here but not in"
        elif number.magnitude != candidates[0].magnitude and not any(
            item.magnitude == number.magnitude for item in candidates
        ):
            problem = "has a different scale than in"
        elif number.currency and not any(item.currency for item in candidates):
            problem = "is a monetary amount here but not in"
        else:
            continue
        issues.append(
            _issue("changed_number", "blocking", f"“{number.raw}” {problem} {evidence.where}.", term=number.raw)
        )
    available_years = _years_claims(evidence.key)
    for years in _years_claims(key) - available_years:
        issues.append(
            _issue(
                "years_claim",
                "blocking",
                f"The claim of {years} years does not appear in {evidence.where}. Years of experience cannot be "
                "added or changed.",
                term=f"{years} years",
            )
        )
    for word in _VAGUE_QUANTITIES:
        if _contains(key, word) and not _contains(evidence.key, word):
            issues.append(
                _issue(
                    "implied_metric",
                    "blocking",
                    f"“{word}” implies a quantity that {evidence.where} does not state.",
                    term=word,
                )
            )
    return issues


def _check_skills(text: str, key: str, evidence: UnitEvidence, ctx: VerificationContext) -> list[VerificationIssue]:
    issues: list[VerificationIssue] = []
    terms: dict[str, str] = {}
    for entry in lexicon.scan(key):
        terms.setdefault(lexicon.canonical(entry.canonical), entry.canonical)
    for name in ambiguous_mentions(text):
        terms.setdefault(lexicon.canonical(name), name)
    categories: dict[str, str] = {}
    if ctx.job is not None:
        for req in ctx.job.requirements:
            if req.category in ("technical_skill", "certification", "soft_skill") and lexicon.mentions(key, req.name):
                terms.setdefault(lexicon.canonical(req.name), req.name)
                categories.setdefault(lexicon.canonical(req.name), req.category)
        for keyword in ctx.job.keywords:
            if lexicon.mentions(key, keyword.term):
                terms.setdefault(lexicon.canonical(keyword.term), keyword.term)
                categories.setdefault(lexicon.canonical(keyword.term), "keyword")

    for canonical, term in terms.items():
        category = categories.get(canonical, "technical_skill")
        if not ctx.mentions_skill(term):
            if category == "keyword":
                issues.append(
                    _issue(
                        "unsupported_keyword",
                        "warning",
                        f"“{term}” is a job keyword that your original resume does not mention.",
                        term=term,
                    )
                )
            elif category == "soft_skill":
                severity = "blocking" if evidence.kind in ("summary", "skills") else "warning"
                issues.append(
                    _issue(
                        "unsupported_skill",
                        severity,
                        f"“{term}” is not evidenced in your original resume. Missing requirements are gaps, "
                        "not claims.",
                        term=term,
                    )
                )
            else:
                issues.append(
                    _issue(
                        "unsupported_qualification" if category == "certification" else "unsupported_skill",
                        "blocking",
                        f"“{term}” is not mentioned anywhere in your original resume. Missing requirements are gaps, "
                        "not claims.",
                        term=term,
                    )
                )
        elif evidence.kind in ("bullet", "project") and not lexicon.mentions(evidence.key, term):
            issues.append(
                _issue(
                    "skill_attribution",
                    "warning",
                    f"“{term}” appears elsewhere in your resume but not in {evidence.where}. Check that you used it "
                    "here.",
                    term=term,
                )
            )
    return issues


def _check_qualifications(text: str, key: str, ctx: VerificationContext) -> list[VerificationIssue]:
    issues: list[VerificationIssue] = []
    for match in _QUALIFICATION.finditer(key):
        if _qualification_group(match.group(1)) not in ctx.qualification_groups:
            issues.append(
                _issue(
                    "unsupported_qualification",
                    "blocking",
                    f"“{match.group(1)}” refers to a qualification your original resume does not mention.",
                    term=match.group(1),
                )
            )
    for match in _CERT_PHRASE.finditer(text):
        phrase = match.group(1).strip()
        if not _contains(ctx.resume_key, phrase):
            issues.append(
                _issue(
                    "unsupported_qualification",
                    "blocking",
                    f"“{phrase}” is not a certification listed in your original resume.",
                    term=phrase,
                )
            )
    return _dedupe(issues)


def _check_names(text: str, key: str, evidence: UnitEvidence, ctx: VerificationContext) -> list[VerificationIssue]:
    issues: list[VerificationIssue] = []
    if ctx.job is not None:
        company = ctx.job.info.company.value if ctx.job.info.company.present else None
        if company and _contains(key, company) and not _contains(ctx.resume_key, company):
            issues.append(
                _issue(
                    "target_employer",
                    "blocking",
                    f"Mentions the target employer “{company}”, which your resume does not.",
                    term=company,
                )
            )
        title = ctx.job.info.title.value if ctx.job.info.title.present else None
        if title and _contains(key, title) and not _contains(ctx.resume_key, title):
            issues.append(
                _issue(
                    "target_title",
                    "blocking",
                    f"Uses the target job title “{title}”, which you have not held according to your resume.",
                    term=title,
                )
            )

    # Organisations need specific support: a bullet's own sources and employer, or for a summary the
    # verified resume structure. Mentions elsewhere in the raw text (which may contain injected
    # instructions) are not enough.
    org_evidence = ctx.document_key if evidence.kind in ("summary", "skills") else evidence.key
    flagged: set[str] = set()
    for pattern in (_ORG_WITH_SUFFIX, _ORG_AFTER_VERB):
        for match in pattern.finditer(text):
            name = match.group(1).strip(" .,'")
            if name.lower() in flagged or _contains(org_evidence, name) or lexicon.lookup(name) is not None:
                continue
            flagged.add(name.lower())
            issues.append(
                _issue(
                    "unsupported_organization",
                    "blocking",
                    f"“{name}” looks like an organisation that does not appear in your resume.",
                    term=name,
                )
            )

    for match in _CAPITALISED.finditer(text):
        word = match.group(1)
        start = match.start()
        before = text[:start].rstrip()
        if not before or before[-1] in ".!?:;\n(—-•*":
            continue  # sentence start
        lowered = word.lower()
        if (
            lowered in flagged
            or lowered in ctx.resume_words
            or f"{lowered}s" in ctx.resume_words
            or lowered.rstrip("s") in ctx.resume_words
            or lowered in STOPWORDS
            or lowered in ACTION_VERBS
            or lexicon.lookup(word) is not None
            or any(lowered in name for name in flagged)
            or _contains(ctx.resume_key, word)
        ):
            continue
        flagged.add(lowered)
        issues.append(
            _issue(
                "unverified_name",
                "warning",
                f"“{word}” does not appear in your original resume. Check that it is accurate.",
                term=word,
            )
        )
    return issues


def _check_claims(key: str, evidence: UnitEvidence, ctx: VerificationContext) -> list[VerificationIssue]:
    issues: list[VerificationIssue] = []
    leadership = _LEADERSHIP.search(key)
    if leadership and not _LEADERSHIP.search(evidence.key):
        issues.append(
            _issue(
                "role_escalation",
                "blocking",
                f"“{leadership.group(1)}” describes leadership or ownership that {evidence.where} does not mention.",
                term=leadership.group(1),
            )
        )
    for word in _SCOPE_WORDS:
        if _contains(key, word) and not _contains(evidence.key, word):
            issues.append(
                _issue(
                    "scope_escalation",
                    "warning",
                    f"“{word}” widens the scope described in {evidence.where}.",
                    term=word,
                )
            )
    for phrase in _SUPERLATIVES:
        if _contains(key, phrase) and not _contains(ctx.resume_key, phrase):
            issues.append(
                _issue(
                    "unverifiable_claim",
                    "warning",
                    f"“{phrase}” is a claim your resume does not support. Prefer concrete evidence.",
                    term=phrase,
                )
            )
    if evidence.kind in ("bullet", "project"):
        produced = _content_stems(key)
        novel = sorted(produced - _content_stems(evidence.key))
        if len(novel) >= 4 and len(novel) > 0.5 * max(len(produced), 1):
            issues.append(
                _issue(
                    "new_content",
                    "warning",
                    f"Much of this wording is not in {evidence.where} ({', '.join(novel[:5])}…). Check it still "
                    "describes what you did.",
                )
            )
    return issues


def _dedupe(issues: Iterable[VerificationIssue]) -> list[VerificationIssue]:
    seen: set[tuple[str, str | None]] = set()
    unique = []
    for issue in issues:
        key = (issue.code, (issue.term or "").lower())
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def check_text(
    text: str,
    evidence: UnitEvidence,
    ctx: VerificationContext,
    *,
    unit: str,
    item_id: str | None = None,
    origin: Origin = "ai",
) -> list[VerificationIssue]:
    """All factual checks for one unit of rewritten text."""

    key = match_key(text)
    issues = [
        *_check_numbers(key, evidence),
        *_check_skills(text, key, evidence, ctx),
        *_check_qualifications(text, key, ctx),
        *_check_names(text, key, evidence, ctx),
        *_check_claims(key, evidence, ctx),
    ]
    return [issue.model_copy(update={"unit": unit, "item_id": item_id, "origin": origin}) for issue in _dedupe(issues)]


def status_of(issues: list[VerificationIssue]) -> str:
    if any(issue.severity == "blocking" for issue in issues):
        return "rejected"
    if any(issue.severity == "warning" for issue in issues):
        return "warning"
    return "verified"


# --------------------------------------------------------------------------- evidence builders


def summary_evidence(ctx: VerificationContext) -> UnitEvidence:
    return UnitEvidence(key=ctx.resume_key, where="your original resume", kind="summary")


def bullet_evidence(ctx: VerificationContext, role: DocExperience | None, source_ids: list[str]) -> UnitEvidence:
    """Evidence for a bullet: the original bullets it cites, plus its role's title and employer."""

    if role is None:
        return UnitEvidence(key=ctx.resume_key, where="your original resume", kind="bullet")
    by_id = {bullet.id: bullet.text for bullet in role.bullets}
    sources = [by_id[source] for source in source_ids if source in by_id]
    where = "the original bullet" if len(sources) == 1 else "the original bullets it rewrites"
    if not sources:
        sources = list(by_id.values())
        where = "this role in your original resume"
    context = [role.title or "", role.employer or ""]
    return UnitEvidence(key=match_key("\n".join([*context, *sources])), where=where, kind="bullet")


def project_evidence(ctx: VerificationContext, project_id: str) -> UnitEvidence:
    project = next((p for p in ctx.original.projects if p.id == project_id), None)
    if project is None:
        return UnitEvidence(key=ctx.resume_key, where="your original resume", kind="project")
    text = "\n".join([project.name or "", project.description or "", ", ".join(project.technologies)])
    return UnitEvidence(key=match_key(text), where="the original project description", kind="project")


# --------------------------------------------------------------------------- whole-document verification


def _changed(a: str | None, b: str | None) -> bool:
    return match_key(a or "") != match_key(b or "")


_LOCKED_EXPERIENCE = ("title", "employer", "location", "start_date", "end_date")
_LOCKED_EDUCATION = ("institution", "qualification", "field_of_study", "start_date", "end_date", "grade")
_LOCKED_CERTIFICATION = ("name", "issuer", "date")
_FIELD_LABELS = {
    "title": "job title", "employer": "employer", "location": "location", "start_date": "start date",
    "end_date": "end date", "institution": "institution", "qualification": "qualification",
    "field_of_study": "field of study", "grade": "grade", "name": "name", "issuer": "issuer", "date": "date",
}  # fmt: skip


def _locked_changes(
    kind: str, item_id: str, current: object, original: object, fields: tuple[str, ...]
) -> list[VerificationIssue]:
    issues = []
    for name in fields:
        new, old = getattr(current, name), getattr(original, name)
        if _changed(new, old):
            issues.append(
                VerificationIssue(
                    code="changed_fact",
                    severity="blocking",
                    message=f"You changed the {_FIELD_LABELS[name]} of this {kind} from “{old or '—'}” to "
                    f"“{new or '—'}”. Make sure it is accurate; it no longer matches your original resume.",
                    term=new,
                    unit=f"{kind}:{item_id}",
                    item_id=item_id,
                    origin="user",
                )
            )
    return issues


def verify_document(
    content: ResumeDocument, ctx: VerificationContext, suggestions: list[Suggestion]
) -> VerificationSummary:
    """Verify the content that would be exported: applied AI suggestions and manual edits."""

    original = ctx.original
    proposed_by_id = {s.id: s for s in suggestions}
    issues: list[VerificationIssue] = []

    def origin_for(text: str, suggestion_ids: Iterable[str]) -> Origin:
        for suggestion_id in suggestion_ids:
            suggestion = proposed_by_id.get(suggestion_id)
            if suggestion is not None and suggestion.proposed == text:
                return "ai"
        return "user"

    # Summary
    if content.summary and _changed(content.summary, original.summary):
        summary_ids = [s.id for s in suggestions if s.unit == "summary"]
        issues += check_text(
            content.summary, summary_evidence(ctx), ctx, unit="summary", origin=origin_for(content.summary, summary_ids)
        )

    # Experience
    original_roles = {entry.id: entry for entry in original.experience}
    for entry in content.experience:
        role = original_roles.get(entry.id)
        unit = f"experience:{entry.id}"
        if role is None:
            issues.append(
                VerificationIssue(
                    code="new_entry",
                    severity="blocking",
                    message=f"“{entry.title or entry.employer or 'This role'}” is not in your original resume. "
                    "Make sure it is accurate.",
                    term=entry.title or entry.employer,
                    unit=unit,
                    item_id=entry.id,
                    origin="user",
                )
            )
        else:
            issues += _locked_changes("experience", entry.id, entry, role, _LOCKED_EXPERIENCE)
        original_bullets = {b.id: b.text for b in role.bullets} if role else {}
        for bullet in entry.bullets:
            if bullet.id in original_bullets and not _changed(bullet.text, original_bullets[bullet.id]):
                continue
            evidence = bullet_evidence(ctx, role, bullet.source_ids)
            issues += check_text(
                bullet.text, evidence, ctx, unit=unit, item_id=bullet.id, origin=origin_for(bullet.text, [bullet.id])
            )
    removed_roles = set(original_roles) - {entry.id for entry in content.experience}
    for role_id in sorted(removed_roles):
        role = original_roles[role_id]
        issues.append(
            VerificationIssue(
                code="entry_removed",
                severity="info",
                message=f"“{role.title or role.employer or role_id}” from your original resume is not included.",
                unit=f"experience:{role_id}",
                item_id=role_id,
                origin="user",
            )
        )

    # Projects
    original_projects = {p.id: p for p in original.projects}
    for project in content.projects:
        base = original_projects.get(project.id)
        unit = f"project:{project.id}"
        if base is None:
            issues.append(
                VerificationIssue(
                    code="new_entry",
                    severity="blocking",
                    message=f"Project “{project.name or project.id}” is not in your original resume.",
                    term=project.name,
                    unit=unit,
                    item_id=project.id,
                    origin="user",
                )
            )
            continue
        if _changed(project.name, base.name):
            issues += _locked_changes("project", project.id, project, base, ("name",))
        added_tech = [t for t in project.technologies if not ctx.mentions_skill(t)]
        for tech in added_tech:
            issues.append(
                VerificationIssue(
                    code="unsupported_skill",
                    severity="blocking",
                    message=f"“{tech}” is not mentioned in your original resume.",
                    term=tech,
                    unit=unit,
                    item_id=project.id,
                    origin="user",
                )
            )
        if project.description and _changed(project.description, base.description):
            ids = [s.id for s in suggestions if s.unit == unit]
            issues += check_text(
                project.description,
                project_evidence(ctx, project.id),
                ctx,
                unit=unit,
                item_id=project.id,
                origin=origin_for(project.description, ids),
            )

    # Education and certifications: facts only, never rewritten by the model.
    original_education = {e.id: e for e in original.education}
    for edu in content.education:
        if edu.id not in original_education:
            issues.append(
                VerificationIssue(
                    code="new_entry",
                    severity="blocking",
                    message=f"“{edu.qualification or edu.institution or 'This qualification'}” is not in your "
                    "original resume.",
                    term=edu.qualification or edu.institution,
                    unit=f"education:{edu.id}",
                    item_id=edu.id,
                    origin="user",
                )
            )
        else:
            issues += _locked_changes("education", edu.id, edu, original_education[edu.id], _LOCKED_EDUCATION)
        issues += _check_coursework(edu, original_education.get(edu.id), ctx)
    original_certs = {c.id: c for c in original.certifications}
    for cert in content.certifications:
        if cert.id not in original_certs:
            issues.append(
                VerificationIssue(
                    code="new_entry",
                    severity="blocking",
                    message=f"Certification “{cert.name or cert.id}” is not in your original resume.",
                    term=cert.name,
                    unit=f"certification:{cert.id}",
                    item_id=cert.id,
                    origin="user",
                )
            )
        else:
            issues += _locked_changes("certification", cert.id, cert, original_certs[cert.id], _LOCKED_CERTIFICATION)

    # Skills
    skill_suggestions = [s for s in suggestions if s.unit == "skills" and s.applied]
    ai_skills = {lexicon.canonical(name) for s in skill_suggestions for name in [*(s.technical or []), *(s.soft or [])]}
    for name in content.technical_skills:
        if not ctx.mentions_skill(name):
            issues.append(
                VerificationIssue(
                    code="unsupported_skill",
                    severity="blocking",
                    message=f"“{name}” is not mentioned in your original resume.",
                    term=name,
                    unit="skills",
                    origin="ai" if lexicon.canonical(name) in ai_skills else "user",
                )
            )
    for name in content.soft_skills:
        if lexicon.canonical(name) not in ctx.soft_skills and not _contains(ctx.resume_key, name):
            issues.append(
                VerificationIssue(
                    code="unsupported_skill",
                    severity="blocking",
                    message=f"“{name}” is not evidenced in your original resume.",
                    term=name,
                    unit="skills",
                    origin="ai" if lexicon.canonical(name) in ai_skills else "user",
                )
            )

    issues = _dedupe_located(issues)
    blocking = sum(1 for issue in issues if issue.severity == "blocking")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    rejected = sum(1 for s in suggestions if s.verification.status == "rejected")
    pending = sum(1 for s in suggestions if s.decision == "pending" and s.verification.status == "warning")
    if blocking:
        status = "unsupported"
    elif warnings or pending:
        status = "needs_review"
    else:
        status = "verified"
    return VerificationSummary(
        status=status,
        blocking=blocking,
        warnings=warnings,
        issues=issues,
        rejected_suggestions=rejected,
        pending_review=pending,
        checks=CHECKS_APPLIED,
    )


def _check_coursework(
    edu: DocEducation, original: DocEducation | None, ctx: VerificationContext
) -> list[VerificationIssue]:
    """Coursework is user-entered: each course must appear in the original resume (its text or its extraction)."""

    known = {match_key(course) for course in (original.coursework if original else [])}
    issues: list[VerificationIssue] = []
    for course in edu.coursework:
        if match_key(course) in known or _contains(ctx.resume_key, course):
            continue
        issues.append(
            VerificationIssue(
                code="unsupported_coursework",
                severity="blocking",
                message=f"Course “{course}” is not mentioned in your original resume.",
                term=course,
                unit=f"education:{edu.id}",
                item_id=edu.id,
                origin="user",
            )
        )
    return issues


def _dedupe_located(issues: list[VerificationIssue]) -> list[VerificationIssue]:
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    unique = []
    for issue in issues:
        key = (issue.code, (issue.term or "").lower(), issue.unit, issue.item_id)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique
