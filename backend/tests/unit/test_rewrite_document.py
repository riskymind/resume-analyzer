"""The editable document: built from the verified extraction, composed from suggestions, rendered for scoring."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.rewrite import (
    DocContact,
    DocLink,
    ResumeDocument,
    RewriteCreate,
    RewriteUpdate,
    Suggestion,
    SuggestionVerification,
)
from app.services.rewriting.document import render_text, to_structured
from app.services.rewriting.scores import compare, quality_report
from app.services.rewriting.service import compose, resolve_bullet_ids
from tests.fixtures.rewrite import AS_OF, sample_document, sample_job_context, sample_structured


def bullet_suggestion(
    sid: str, sources: list[str], text: str, *, status: str = "verified", decision: str = "pending"
) -> Suggestion:
    return Suggestion(
        id=sid,
        unit="experience:exp-1",
        section="experience",
        item_id="exp-1",
        kind="bullet",
        original=None,
        proposed=text,
        source_ids=sources,
        verification=SuggestionVerification(status=status),
        decision=decision,
    )


class TestBuildAndRender:
    def test_document_has_stable_ids_and_original_order(self) -> None:
        document = sample_document()
        assert [e.id for e in document.experience] == ["exp-1", "exp-2"]
        assert [b.id for b in document.experience[0].bullets] == ["exp-1-b1", "exp-1-b2"]
        assert document.experience[0].bullets[0].text.startswith("Led migration")
        assert document.experience[0].employer == "Acme Corp"
        assert document.contact.email == "jane.doe@example.com"

    def test_render_text_is_detected_by_the_section_parser(self) -> None:
        text = render_text(sample_document())
        for heading in ("## Summary", "## Experience", "## Skills", "## Education"):
            assert heading in text
        assert "- Led migration of 40 services" in text

    def test_to_structured_round_trip_keeps_facts(self) -> None:
        structured = to_structured(sample_document(), original=sample_structured())
        assert structured.experience[0].employer.value == "Acme Corp"
        assert structured.experience[0].achievements[0].metrics == ["40", "35%"]
        assert structured.soft_skills[0].evidence  # soft-skill evidence carried over from extraction

    def test_same_content_scores_the_same(self) -> None:
        document = sample_document()
        first = quality_report(document, original=sample_structured())
        second = quality_report(document.model_copy(deep=True), original=sample_structured())
        assert first == second

    def test_compare_uses_deterministic_engines_for_both_sides(self) -> None:
        job = sample_job_context()
        comparison = compare(
            original_doc=sample_document(),
            content=sample_document(),
            original_structured=sample_structured(),
            job=job,
            uploaded_score=None,
            saved_match_score=None,
            as_of=AS_OF,
        )
        assert comparison.quality.before == comparison.quality.after
        assert comparison.match is not None
        assert comparison.match.before == comparison.match.after
        assert "Terraform" in comparison.match.still_missing
        assert "does not guarantee an interview" in comparison.disclaimer


class TestCompose:
    def test_applied_and_rejected_suggestions(self) -> None:
        original = sample_document()
        suggestions = [
            bullet_suggestion("g1-s1", ["exp-1-b1"], "Led the migration of 40 services to Kubernetes."),
            bullet_suggestion("g1-s2", ["exp-1-b2"], "Built FastAPI services.", decision="rejected"),
        ]
        content = compose(original, original, suggestions, {"experience:exp-1"})
        assert [(b.id, b.text) for b in content.experience[0].bullets] == [
            ("g1-s1", "Led the migration of 40 services to Kubernetes."),
            ("exp-1-b2", "Built FastAPI services handling 2M requests per day."),
        ]
        assert original.experience[0].bullets[0].text.startswith("Led migration")  # original untouched

    def test_warning_suggestions_wait_for_acceptance(self) -> None:
        original = sample_document()
        pending = bullet_suggestion("g1-s1", ["exp-1-b1"], "Rewritten.", status="warning")
        assert compose(original, original, [pending], {"experience:exp-1"}).experience[0].bullets[0].id == "exp-1-b1"
        accepted = pending.model_copy(update={"decision": "accepted"})
        assert compose(original, original, [accepted], {"experience:exp-1"}).experience[0].bullets[0].id == "g1-s1"

    def test_blocked_suggestions_never_apply_even_if_accepted(self) -> None:
        original = sample_document()
        blocked = bullet_suggestion("g1-s1", ["exp-1-b1"], "Fabricated.", status="rejected", decision="accepted")
        assert compose(original, original, [blocked], {"experience:exp-1"}).experience[0].bullets[0].id == "exp-1-b1"

    def test_merged_bullets_replace_both_sources(self) -> None:
        original = sample_document()
        merged = bullet_suggestion("g1-s1", ["exp-1-b2", "exp-1-b1"], "Merged bullet.")
        bullets = compose(original, original, [merged], {"experience:exp-1"}).experience[0].bullets
        assert [(b.id, b.source_ids) for b in bullets] == [("g1-s1", ["exp-1-b2", "exp-1-b1"])]

    def test_recomposing_one_unit_keeps_manual_edits_elsewhere(self) -> None:
        original = sample_document()
        content = original.model_copy(deep=True)
        content.experience[1].bullets[0].text = "Maintained PostgreSQL data pipelines (edited)."
        composed = compose(content, original, [bullet_suggestion("g1-s1", ["exp-1-b1"], "New.")], {"experience:exp-1"})
        assert composed.experience[1].bullets[0].text.endswith("(edited).")

    def test_resolve_bullet_ids(self) -> None:
        original = sample_document()
        content = compose(original, original, [bullet_suggestion("g1-s1", ["exp-1-b1"], "New.")], {"experience:exp-1"})
        assert resolve_bullet_ids(["g1-s1", "exp-1-b2"], original, content) == ["exp-1-b1", "exp-1-b2"]


class TestSchemas:
    def test_links_must_be_web_urls(self) -> None:
        with pytest.raises(ValidationError):
            DocLink(kind="website", url="javascript:alert(1)")
        assert DocLink(kind="website", url="https://example.com/x").url == "https://example.com/x"

    def test_email_shape(self) -> None:
        with pytest.raises(ValidationError):
            DocContact(email="not an email")

    def test_duplicate_ids_rejected(self) -> None:
        data = sample_document().model_dump()
        data["experience"][1]["id"] = "exp-1"
        with pytest.raises(ValidationError, match="unique"):
            ResumeDocument.model_validate(data)

    def test_unknown_fields_rejected(self) -> None:
        data = sample_document().model_dump()
        data["experience"][0]["salary"] = "1M"
        with pytest.raises(ValidationError):
            ResumeDocument.model_validate(data)

    @pytest.mark.parametrize(
        "body",
        [
            {"resume_id": "r", "scope": "bullets"},
            {"resume_id": "r", "scope": "summary", "bullet_ids": ["exp-1-b1"]},
            {"resume_id": "r", "scope": "keywords"},
            {"resume_id": "r", "mode": "job_targeted"},
            {"resume_id": "r", "scope": "bullets", "bullet_ids": ["../../etc"]},
        ],
    )
    def test_invalid_create_requests(self, body: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            RewriteCreate.model_validate(body)

    def test_update_needs_exactly_one_change(self) -> None:
        with pytest.raises(ValidationError):
            RewriteUpdate.model_validate({"base_version": 1})
        with pytest.raises(ValidationError):
            RewriteUpdate.model_validate({"base_version": 1, "decisions": {}, "restore_version": 1})
        assert RewriteUpdate.model_validate({"base_version": 1, "name": "x"}).name == "x"
