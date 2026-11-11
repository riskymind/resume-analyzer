"""AI rewrite generation: build the minimal prompt input, call the provider, validate, verify.

The model proposes wording by item id. This module turns each proposal into a
:class:`Suggestion` and verifies it against the original resume before it can
reach the document. Proposals that reference unknown items, fall outside the
requested scope or are malformed are discarded and counted.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.ai.base import AIProvider, AIProviderError
from app.ai.rewrite_prompts import PROMPT_VERSION_REWRITE, build_rewrite_prompt
from app.ai.structured import parse_model_output, response_schema
from app.core.errors import AIUpstreamError, AppError
from app.schemas.job import StructuredJob
from app.schemas.matching import MatchReport
from app.schemas.rewrite import (
    SCOPE_SECTIONS,
    AIRewriteOutput,
    Gap,
    GenerationInfo,
    MetricPrompt,
    ResumeDocument,
    RewriteMode,
    RewriteScope,
    Suggestion,
    SuggestionVerification,
    VerificationIssue,
)
from app.services.extraction import clean_value, match_key
from app.services.matching import skills as lexicon
from app.services.rewriting.document import certification_line, education_line
from app.services.rewriting.verification import (
    VerificationContext,
    bullet_evidence,
    check_text,
    project_evidence,
    status_of,
    summary_evidence,
)

logger = logging.getLogger(__name__)

# Output cap for one rewrite generation (thinking tokens included); see services/extraction.py.
MAX_OUTPUT_TOKENS_REWRITE = 32_768

_MAX_NOTES = 6
_MAX_NOTE_CHARS = 300


@dataclass
class JobContext:
    """The target job and the deterministic match of the *original* resume against it."""

    job_id: str
    job: StructuredJob
    report: MatchReport

    @property
    def title(self) -> str | None:
        return self.job.info.title.value if self.job.info.title.present else None

    @property
    def missing_ids(self) -> set[str]:
        return {r.requirement_id for r in self.report.requirements if r.status == "missing"}


@dataclass
class Generation:
    suggestions: list[Suggestion]
    info: GenerationInfo
    sections: list[str] = field(default_factory=list)


def default_mode(job: JobContext | None) -> RewriteMode:
    return "job_targeted" if job is not None else "professional"


def sections_for(scope: RewriteScope, original: ResumeDocument) -> list[str]:
    """Sections the scope covers that the resume actually has something to rewrite in."""

    available = {
        "summary": bool(original.summary or original.experience),
        "experience": any(entry.bullets for entry in original.experience),
        "skills": bool(original.technical_skills or original.soft_skills),
        "projects": any(p.description for p in original.projects),
        "education": len(original.education) > 1 or len(original.certifications) > 1,
    }
    return [section for section in SCOPE_SECTIONS[scope] if available.get(section)]


# --------------------------------------------------------------------------- prompt payloads


def resume_payload(original: ResumeDocument) -> dict[str, object]:
    """The resume as the model sees it: content with ids, without contact details or organisation names."""

    return {
        "summary": {"id": "summary", "text": original.summary},
        "experience": [
            {
                "id": entry.id,
                "title": entry.title,
                "start_date": entry.start_date,
                "end_date": entry.end_date,
                "bullets": [{"id": bullet.id, "text": bullet.text} for bullet in entry.bullets],
            }
            for entry in original.experience
        ],
        "projects": [
            {"id": p.id, "name": p.name, "description": p.description, "technologies": p.technologies}
            for p in original.projects
        ],
        "skills": {"technical": original.technical_skills, "soft": original.soft_skills},
        "education": [
            {"id": e.id, "qualification": e.qualification, "field_of_study": e.field_of_study, "end_date": e.end_date}
            for e in original.education
        ],
        "certifications": [{"id": c.id, "name": c.name, "date": c.date} for c in original.certifications],
    }


_IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def job_payload(ctx: JobContext) -> dict[str, object]:
    """Requirements (mandatory first) and what the original resume does and does not evidence.

    The employer's name is not sent: the rewrite must never mention it.
    """

    requirements = sorted(
        (r for r in ctx.job.requirements),
        key=lambda r: (r.classification != "required", _IMPORTANCE_ORDER[r.importance]),
    )
    results = {r.requirement_id: r for r in ctx.report.requirements}
    evidenced = [rid for rid, r in results.items() if r.status in ("matched", "partial") and r.counted]
    related = [
        {"id": rid, "requirement": r.name, "resume_has": r.related_to}
        for rid, r in results.items()
        if r.status == "related" and r.counted
    ]
    not_evidenced = [r.name for r in ctx.report.requirements if r.status == "missing" and r.counted]
    return {
        "title": ctx.title,
        "seniority": ctx.job.info.seniority.value if ctx.job.info.seniority.present else None,
        "requirements": [
            {
                "id": r.id,
                "name": r.name,
                "category": r.category,
                "classification": r.classification,
                "importance": r.importance,
            }
            for r in requirements
        ],
        "evidenced_requirement_ids": evidenced,
        "related_but_not_equivalent": related,
        "not_evidenced": not_evidenced,
        "keywords_in_resume": ctx.report.keywords.present,
        "keywords_not_in_resume": ctx.report.keywords.missing,
    }


def gaps_for(ctx: JobContext | None) -> list[Gap]:
    if ctx is None:
        return []
    gaps = []
    for result in ctx.report.requirements:
        if not result.counted or result.status not in ("missing", "related"):
            continue
        if result.status == "missing":
            message = (
                f"Your resume shows no evidence of “{result.name}”. It was not added to the rewrite; add it yourself "
                "only if it is true."
            )
        else:
            message = (
                f"You have related experience ({result.related_to}), which is not the same as “{result.name}”. "
                "The rewrite does not claim it."
            )
        gaps.append(
            Gap(
                requirement_id=result.requirement_id,
                name=result.name,
                category=result.category,
                classification=result.classification,
                message=message,
            )
        )
    return gaps


# --------------------------------------------------------------------------- parsing and suggestion building


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text.lstrip("-•*· ").strip() or None


def _verified_keywords(text: str, keywords: list[str]) -> list[str]:
    key = match_key(text)
    kept: list[str] = []
    for keyword in keywords:
        cleaned = clean_value(keyword)
        present = cleaned and len(cleaned) <= 80 and (lexicon.mentions(key, cleaned) or match_key(cleaned) in key)
        if present and cleaned and cleaned.lower() not in {k.lower() for k in kept}:
            kept.append(cleaned)
    return kept[:10]


class _Builder:
    def __init__(
        self,
        *,
        original: ResumeDocument,
        vctx: VerificationContext,
        job: JobContext | None,
        generation: int,
    ) -> None:
        self.original = original
        self.vctx = vctx
        self.job = job
        self.generation = generation
        self.suggestions: list[Suggestion] = []
        self.metric_prompts: list[MetricPrompt] = []
        self.discarded = 0
        self._valid_requirements = {r.id for r in job.job.requirements} if job else set()
        self._missing = job.missing_ids if job else set()

    def _requirement_ids(self, ids: list[str]) -> list[str]:
        return [rid for rid in dict.fromkeys(ids) if rid in self._valid_requirements and rid not in self._missing]

    def add(self, **fields: object) -> None:
        issues: list[VerificationIssue] = fields.pop("issues", [])  # type: ignore[assignment]
        status = status_of(issues)
        suggestion = Suggestion(
            id=f"g{self.generation}-s{len(self.suggestions) + 1}",
            verification=SuggestionVerification(status=status, issues=issues),
            decision="rejected" if status == "rejected" else "pending",
            auto_rejected=status == "rejected",
            generation=self.generation,
            **fields,
        )
        self.suggestions.append(suggestion)

    # ----------------------------------------------------------------- sections

    def summary(self, output: AIRewriteOutput) -> None:
        if output.summary is None:
            return
        text = _clean_text(output.summary.text)
        if text is None or match_key(text) == match_key(self.original.summary or ""):
            return
        self.add(
            unit="summary",
            section="summary",
            kind="text",
            original=self.original.summary,
            proposed=text,
            rationale=_clean_text(output.summary.rationale),
            keywords=_verified_keywords(text, output.summary.keywords),
            requirement_ids=self._requirement_ids(output.summary.requirement_ids),
            issues=check_text(text, summary_evidence(self.vctx), self.vctx, unit="summary"),
        )

    def experience(self, output: AIRewriteOutput, selected: set[str] | None) -> None:
        roles = {entry.id: entry for entry in self.original.experience}
        for role_out in output.experience:
            role = roles.get(role_out.id)
            if role is None:
                self.discarded += 1 + len(role_out.bullets)
                continue
            texts = {bullet.id: bullet.text for bullet in role.bullets}
            unit = f"experience:{role.id}"
            for bullet in role_out.bullets:
                text = _clean_text(bullet.text)
                source_ids = [sid for sid in dict.fromkeys(bullet.source_ids) if sid in texts]
                if text is None or (selected is not None and (not source_ids or not set(source_ids) <= selected)):
                    self.discarded += 1
                    continue
                if len(source_ids) == 1 and match_key(text) == match_key(texts[source_ids[0]]):
                    continue  # unchanged
                issues = check_text(
                    text, bullet_evidence(self.vctx, role, source_ids), self.vctx, unit=unit, item_id=None
                )
                if not source_ids:
                    issues.append(
                        VerificationIssue(
                            code="no_source",
                            severity="blocking",
                            message="This bullet does not rewrite any bullet from your original resume.",
                            unit=unit,
                        )
                    )
                prompt = _clean_text(bullet.metric_prompt)
                if prompt and (re.search(r"\d", prompt) or len(prompt) > 200):
                    prompt = None  # questions may not suggest figures
                suggestion_id = f"g{self.generation}-s{len(self.suggestions) + 1}"
                self.add(
                    unit=unit,
                    section="experience",
                    item_id=role.id,
                    kind="bullet",
                    original="\n".join(texts[sid] for sid in source_ids) or None,
                    proposed=text,
                    source_ids=source_ids,
                    rationale=_clean_text(bullet.rationale),
                    keywords=_verified_keywords(text, bullet.keywords),
                    requirement_ids=self._requirement_ids(bullet.requirement_ids),
                    metric_prompt=prompt,
                    issues=[issue.model_copy(update={"item_id": suggestion_id}) for issue in issues],
                )
                if prompt:
                    self.metric_prompts.append(MetricPrompt(item_id=suggestion_id, bullet=text, question=prompt))

    def skills(self, output: AIRewriteOutput) -> None:
        if output.skills is None:
            return
        issues: list[VerificationIssue] = []

        def reorder(proposed: list[str], existing: list[str], label: str) -> list[str]:
            by_key = {lexicon.canonical(name): name for name in existing}
            ordered: list[str] = []
            for raw in proposed:
                name = clean_value(raw)
                if not name:
                    continue
                key = lexicon.canonical(name)
                if key in by_key:
                    if by_key[key] not in ordered:
                        ordered.append(by_key[key])
                else:
                    issues.append(
                        VerificationIssue(
                            code="unsupported_skill",
                            severity="blocking",
                            message=f"“{name}” is not one of your listed {label} skills, so it was removed.",
                            term=name,
                            unit="skills",
                            action="removed",
                        )
                    )
            return ordered + [name for name in existing if name not in ordered]

        technical = reorder(output.skills.technical, self.original.technical_skills, "technical")
        soft = reorder(output.skills.soft, self.original.soft_skills, "soft")
        if technical == self.original.technical_skills and soft == self.original.soft_skills:
            return
        # Removed items never reach the proposal, so they do not block the reordering itself.
        flagged = [issue.model_copy(update={"severity": "info"}) for issue in issues]
        self.add(
            unit="skills",
            section="skills",
            kind="skills",
            original=_skills_text(self.original.technical_skills, self.original.soft_skills),
            proposed=_skills_text(technical, soft),
            technical=technical,
            soft=soft,
            rationale=_clean_text(output.skills.rationale),
            issues=flagged,
        )

    def projects(self, output: AIRewriteOutput) -> None:
        projects = {p.id: p for p in self.original.projects}
        for project_out in output.projects:
            project = projects.get(project_out.id)
            text = _clean_text(project_out.description)
            if project is None or text is None:
                self.discarded += 1
                continue
            if match_key(text) == match_key(project.description or ""):
                continue
            unit = f"project:{project.id}"
            self.add(
                unit=unit,
                section="projects",
                item_id=project.id,
                kind="text",
                original=project.description,
                proposed=text,
                rationale=_clean_text(project_out.rationale),
                keywords=_verified_keywords(text, project_out.keywords),
                requirement_ids=self._requirement_ids(project_out.requirement_ids),
                issues=check_text(
                    text, project_evidence(self.vctx, project.id), self.vctx, unit=unit, item_id=project.id
                ),
            )

    def orders(self, output: AIRewriteOutput) -> None:
        for section, ids, items, label in (
            ("education", output.education_order, self.original.education, education_line),
            ("certifications", output.certification_order, self.original.certifications, certification_line),
        ):
            if ids is None or len(items) < 2:
                continue
            known = [item.id for item in items]
            order = [item_id for item_id in dict.fromkeys(ids) if item_id in known]
            self.discarded += len(ids) - len(order)
            order += [item_id for item_id in known if item_id not in order]
            if order == known:
                continue
            by_id = {item.id: item for item in items}
            self.add(
                unit=section,
                section=section,
                kind="order",
                original=" · ".join(_line(label, by_id[item_id]) for item_id in known),
                proposed=" · ".join(_line(label, by_id[item_id]) for item_id in order),
                order=order,
                rationale="Most relevant first. Content is unchanged.",
                issues=[],
            )

    def notes(self, output: AIRewriteOutput) -> list[str]:
        """The model's explanation, shown as commentary. Notes making unsupported claims are dropped."""

        kept = []
        for note in output.alignment_notes[:_MAX_NOTES]:
            text = _clean_text(note)
            if not text:
                continue
            text = text[:_MAX_NOTE_CHARS]
            issues = check_text(text, summary_evidence(self.vctx), self.vctx, unit="notes")
            if not any(issue.severity == "blocking" for issue in issues):
                kept.append(text)
        return kept


def _line(render: object, item: object) -> str:
    return render(item)  # type: ignore[operator, no-any-return]


def _skills_text(technical: list[str], soft: list[str]) -> str:
    lines = []
    if technical:
        lines.append("Technical: " + ", ".join(technical))
    if soft:
        lines.append("Soft: " + ", ".join(soft))
    return "\n".join(lines)


# --------------------------------------------------------------------------- entry point

_KEYWORD_FOCUS = (
    "Targeted keyword optimisation: make the smallest edits that work the job's evidenced keywords "
    "('keywords_in_resume') into the summary, bullets and skills order where they fit naturally. Do not rewrite "
    "text that already reads well, and never use 'keywords_not_in_resume'."
)


def generate(
    provider: AIProvider,
    *,
    original: ResumeDocument,
    vctx: VerificationContext,
    job: JobContext | None,
    scope: RewriteScope,
    mode: RewriteMode,
    bullet_ids: list[str],
    generation: int,
) -> Generation:
    sections = sections_for(scope, original)
    if not sections:
        raise AppError("There is nothing to rewrite in the selected scope for this resume.", code="nothing_to_rewrite")
    selected = set(bullet_ids) if scope == "bullets" else None
    system, prompt = build_rewrite_prompt(
        resume=resume_payload(original),
        job=job_payload(job) if job is not None else None,
        sections=sections,
        mode=mode,
        bullet_ids=bullet_ids,
        extra_instructions=[_KEYWORD_FOCUS] if scope == "keywords" else None,
    )
    try:
        raw = provider.generate_json(
            system=system,
            prompt=prompt,
            json_schema=response_schema(AIRewriteOutput, optional_sections=True),
            max_output_tokens=MAX_OUTPUT_TOKENS_REWRITE,
            task=f"rewrite_{scope}",
        )
    except AIProviderError as exc:
        raise AIUpstreamError(str(exc)) from exc
    output = parse_model_output(
        raw,
        AIRewriteOutput,
        provider=provider.name,
        task=f"rewrite_{scope}",
        prompt_version=PROMPT_VERSION_REWRITE,
        user_message="The AI provider returned an unexpected rewrite format. Please try again.",
    )

    builder = _Builder(original=original, vctx=vctx, job=job, generation=generation)
    if "summary" in sections:
        builder.summary(output)
    if "experience" in sections:
        builder.experience(output, selected)
    if "skills" in sections:
        builder.skills(output)
    if "projects" in sections:
        builder.projects(output)
    if "education" in sections:
        builder.orders(output)

    info = GenerationInfo(
        generation=generation,
        scope=scope,
        mode=mode,
        bullet_ids=bullet_ids,
        provider=provider.name,
        prompt_version=PROMPT_VERSION_REWRITE,
        alignment_notes=builder.notes(output) if job is not None else [],
        gaps=gaps_for(job),
        metric_prompts=builder.metric_prompts,
        discarded_items=builder.discarded,
    )
    if not builder.suggestions:
        info.warnings.append("The AI did not propose any changes for this scope.")
    rejected = sum(1 for s in builder.suggestions if s.auto_rejected)
    if rejected:
        info.warnings.append(
            f"{rejected} suggestion(s) were rejected automatically because they made claims your resume does not "
            "support. You can review them below."
        )
    logger.info(
        "rewrite_generated",
        extra={
            "provider": provider.name,
            "scope": scope,
            "mode": mode,
            "suggestions": len(builder.suggestions),
            "auto_rejected": rejected,
            "discarded": builder.discarded,
        },
    )
    return Generation(suggestions=builder.suggestions, info=info, sections=sections)
