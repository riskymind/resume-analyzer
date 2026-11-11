"""Before/after scores, recalculated from saved content by the existing deterministic engines.

No score comes from the AI. Both the original and the rewritten document are
rendered through the same canonical layout (:func:`render_text`) before
scoring, so the comparison measures the content change, not a difference in
file formatting. Job matching runs with semantic similarity *disabled* for
both sides. Embeddings would need new AI calls for every edit, and the two
sides must be measured identically.
"""

from __future__ import annotations

from datetime import date

from app.parsing.files import ExtractedDocument
from app.parsing.sections import detect_sections
from app.schemas.matching import MatchReport, SemanticSignals
from app.schemas.resume import StructuredResume
from app.schemas.rewrite import MatchComparison, QualityComparison, ResumeDocument, ScoreComparison
from app.schemas.scoring import QualityReport
from app.services.matching.engine import match_resume_to_job
from app.services.rewriting.document import render_text, to_structured
from app.services.rewriting.generator import JobContext
from app.services.scoring.engine import ScoringInput, score_resume

MATCH_METHOD = (
    "Deterministic requirement matching (exact, alias and skill-family rules). Semantic similarity is excluded for "
    "both versions so they are measured identically; a saved match report may differ for that reason."
)

_DISABLED = SemanticSignals(status="disabled", reason="Excluded from before/after comparisons.")


def quality_report(document: ResumeDocument, *, original: StructuredResume) -> QualityReport:
    text = render_text(document)
    extracted = ExtractedDocument(format="docx", text=text, body_text=text, content_sha256="")
    return score_resume(
        ScoringInput(
            document=extracted, layout=detect_sections(text), structured=to_structured(document, original=original)
        )
    )


def match_report(document: ResumeDocument, job: JobContext, *, original: StructuredResume, as_of: date) -> MatchReport:
    return match_resume_to_job(
        to_structured(document, original=original), render_text(document), job.job, _DISABLED, as_of=as_of
    )


def compare(
    *,
    original_doc: ResumeDocument,
    content: ResumeDocument,
    original_structured: StructuredResume,
    job: JobContext | None,
    uploaded_score: int | None,
    saved_match_score: int | None,
    as_of: date,
) -> ScoreComparison:
    before = quality_report(original_doc, original=original_structured)
    after = quality_report(content, original=original_structured)
    comparison = ScoreComparison(
        quality=QualityComparison(
            before=before.overall_score,
            after=after.overall_score,
            before_ats=before.ats_score,
            after_ats=after.ats_score,
            before_label=before.label,
            after_label=after.label,
            uploaded_score=uploaded_score,
        )
    )
    if job is None:
        return comparison

    match_before = match_report(original_doc, job, original=original_structured, as_of=as_of)
    match_after = match_report(content, job, original=original_structured, as_of=as_of)
    credit_before = {r.requirement_id: r.credit for r in match_before.requirements}
    comparison.match = MatchComparison(
        job_id=job.job_id,
        job_title=job.title,
        before=match_before.match_score,
        after=match_after.match_score,
        before_label=match_before.label,
        after_label=match_after.label,
        newly_evidenced=[
            r.name
            for r in match_after.requirements
            if r.counted and r.credit > credit_before.get(r.requirement_id, 0.0) + 1e-9
        ],
        still_missing=[r.name for r in match_after.requirements if r.counted and r.status == "missing"],
        saved_match_score=saved_match_score,
        method=MATCH_METHOD,
    )
    before_keywords = {k.lower() for k in match_before.keywords.present}
    comparison.keywords_incorporated = [k for k in match_after.keywords.present if k.lower() not in before_keywords]
    return comparison
