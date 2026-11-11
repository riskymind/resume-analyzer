"""Deterministic job matching engine: evidence-based, explainable, reproducible."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.schemas.job import JobExtractionInfo, JobKeyword, JobRequirement, StructuredJob
from app.schemas.matching import MatchReport, SemanticPair, SemanticSignals
from app.schemas.resume import (
    Bullet,
    Certification,
    EducationEntry,
    ExperienceEntry,
    ExtractionInfo,
    Skill,
    StructuredResume,
    TextField,
)
from app.services.matching.config import MatchingConfig
from app.services.matching.engine import match_resume_to_job

AS_OF = date(2026, 11, 8)
AVAILABLE = SemanticSignals(status="available", model="fake:fake-embedding-1")


def tf(value: str | None) -> TextField:
    return TextField(value=value, status="explicit", evidence=value) if value else TextField()


def role(title: str, employer: str, start: str, end: str, *bullets: str) -> ExperienceEntry:
    return ExperienceEntry(
        title=tf(title),
        employer=tf(employer),
        start_date=tf(start),
        end_date=tf(end),
        responsibilities=[Bullet(text=b, kind="responsibility") for b in bullets],
    )


def make_resume(
    *,
    skills: tuple[str, ...] = ("Python", "Django", "PostgreSQL", "k8s", "AWS"),
    soft: tuple[str, ...] = (),
    experience: list[ExperienceEntry] | None = None,
    education: list[EducationEntry] | None = None,
    certifications: tuple[str, ...] = (),
    summary: str | None = "Backend engineer with 6 years of experience building Python APIs.",
) -> tuple[StructuredResume, str]:
    experience = (
        experience
        if experience is not None
        else [
            role("Senior Software Engineer", "Acme", "Jan 2021", "Present", "Built Django REST services in Python."),
            role("Software Engineer", "Initech", "Mar 2018", "Dec 2020", "Maintained PostgreSQL data pipelines."),
        ]
    )
    education = (
        education
        if education is not None
        else [
            EducationEntry(
                institution=tf("State University"), qualification=tf("BSc"), field_of_study=tf("Computer Science")
            )
        ]
    )
    resume = StructuredResume(
        summary=tf(summary),
        experience=experience,
        education=education,
        technical_skills=[Skill(name=s, status="explicit") for s in skills],
        soft_skills=[Skill(name=s, status="explicit") for s in soft],
        certifications=[Certification(name=tf(c)) for c in certifications],
        extraction=ExtractionInfo(provider="fake", prompt_version="test"),
    )
    lines = [summary or "", *(f"{e.title.value} {e.employer.value}" for e in experience)]
    lines += [b.text for e in experience for b in e.bullets]
    lines += [", ".join(skills), ", ".join(soft), *certifications]
    lines += [f"{e.qualification.value} {e.field_of_study.value}" for e in education]
    return resume, "\n".join(lines)


def r(
    rid: str,
    name: str,
    category: str = "technical_skill",
    classification: str = "required",
    *,
    importance: str = "medium",
    evidence: str | None = None,
    **extra: Any,
) -> JobRequirement:
    return JobRequirement(
        id=rid,
        name=name,
        category=category,
        classification=classification,
        classification_source="text",
        importance=importance,
        evidence=evidence or name,
        status="verified",
        **extra,
    )


def make_job(*requirements: JobRequirement, keywords: tuple[str, ...] = ()) -> StructuredJob:
    return StructuredJob(
        requirements=list(requirements),
        keywords=[JobKeyword(term=k) for k in keywords],
        extraction=JobExtractionInfo(provider="fake", prompt_version="test"),
    )


def run(
    job: StructuredJob,
    resume: tuple[StructuredResume, str] | None = None,
    signals: SemanticSignals = AVAILABLE,
    config: MatchingConfig | None = None,
) -> MatchReport:
    structured, text = resume or make_resume()
    kwargs = {"config": config} if config else {}
    return match_resume_to_job(structured, text, job, signals, as_of=AS_OF, **kwargs)


def result(report: MatchReport, rid: str) -> Any:
    return next(x for x in report.requirements if x.requirement_id == rid)


class TestSkills:
    def test_exact_and_alias_matches_carry_resume_evidence(self) -> None:
        report = run(make_job(r("r1", "Django"), r("r2", "Kubernetes")))
        for rid in ("r1", "r2"):
            item = result(report, rid)
            assert (item.status, item.match_type, item.credit) == ("matched", "exact", 1.0)
            assert item.evidence, "every match must point at resume evidence"
        assert report.match_score == 100

    def test_related_skill_is_not_an_exact_match(self) -> None:
        report = run(make_job(r("r1", "FastAPI")))
        item = result(report, "r1")
        assert item.status == "related"
        assert item.match_type == "related_lexicon"
        assert item.related_to == "Django"
        assert item.credit == pytest.approx(0.35)
        assert "not treated as having FastAPI" in item.explanation
        assert [s.name for s in report.skills.exact] == []
        assert [s.name for s in report.skills.related] == ["FastAPI"]

    def test_semantic_similarity_above_threshold_is_related_never_exact(self) -> None:
        signals = SemanticSignals(
            status="available", skill_pairs={"r1": SemanticPair(resume_text="PostgreSQL", similarity=0.91)}
        )
        item = result(run(make_job(r("r1", "CockroachDB")), signals=signals), "r1")
        assert (item.status, item.match_type, item.similarity) == ("related", "related_semantic", 0.91)

    def test_semantic_similarity_below_threshold_is_missing(self) -> None:
        signals = SemanticSignals(
            status="available", skill_pairs={"r1": SemanticPair(resume_text="PostgreSQL", similarity=0.79)}
        )
        assert result(run(make_job(r("r1", "CockroachDB")), signals=signals), "r1").status == "missing"

    def test_semantic_pairs_ignored_when_unavailable(self) -> None:
        signals = SemanticSignals(
            status="unavailable",
            reason="timeout",
            skill_pairs={"r1": SemanticPair(resume_text="PostgreSQL", similarity=0.95)},
        )
        report = run(make_job(r("r1", "CockroachDB"), r("r2", "Python"), r("r3", "Django")), signals=signals)
        assert result(report, "r1").status == "missing"
        assert report.semantic.status == "unavailable"
        assert report.confidence.level == "medium"
        assert any("unavailable" in reason for reason in report.confidence.reasons)

    def test_missing_skill_explains_missing_evidence_not_absence(self) -> None:
        item = result(run(make_job(r("r1", "Rust"))), "r1")
        assert item.status == "missing"
        assert item.credit == 0
        assert item.evidence == []
        assert "may still have it" in item.explanation

    def test_ambiguous_skill_requires_an_explicit_skill_list_entry(self) -> None:
        resume = make_resume(summary="Ready to go the extra mile.")
        assert result(run(make_job(r("r1", "Go")), resume=resume), "r1").status == "missing"
        resume = make_resume(skills=("Go",))
        assert result(run(make_job(r("r1", "Go")), resume=resume), "r1").status == "matched"

    def test_soft_skill_demonstrated_by_inferred_evidence(self) -> None:
        structured, text = make_resume()
        structured.soft_skills = [Skill(name="Leadership", status="inferred", evidence="Led a team of five engineers.")]
        item = result(run(make_job(r("r1", "Leadership", "soft_skill")), resume=(structured, text)), "r1")
        assert (item.status, item.match_type) == ("matched", "evidenced")
        assert item.evidence[0].text == "Led a team of five engineers."

    def test_alternatives_are_scored_once_by_the_best_member(self) -> None:
        job = make_job(
            r("r1", "FastAPI", alternative_group="g1"), r("r2", "Django", alternative_group="g1"), r("r3", "Python")
        )
        report = run(job)
        assert report.match_score == 100
        fastapi = result(report, "r1")
        assert fastapi.counted is False
        assert fastapi.satisfied_by_alternative == "Django"
        assert report.skills.missing == []
        assert report.score_cap is None


class TestScoringRules:
    def test_required_outweighs_preferred(self) -> None:
        missing_required = run(make_job(r("r1", "Rust"), r("r2", "Django", classification="preferred")))
        missing_preferred = run(make_job(r("r1", "Django"), r("r2", "Rust", classification="preferred")))
        assert missing_preferred.match_score > missing_required.match_score

    def test_missing_mandatory_requirement_caps_below_strong(self) -> None:
        job = make_job(
            *(r(f"r{i}", s) for i, s in enumerate(["Python", "Django", "PostgreSQL", "AWS"], 1)),
            r("r5", "Rust", importance="low"),
        )
        report = run(job, config=MatchingConfig())
        assert report.match_score == 79
        assert report.label != "Strong Match"
        assert report.score_cap
        assert "1 mandatory requirement" in report.score_cap

    def test_majority_of_mandatory_missing_caps_at_59(self) -> None:
        # Keyword-heavy weights would put this at 71 without the cap.
        config = MatchingConfig(
            version="test-keyword-heavy",
            weights={
                "required_skills": 30,
                "experience": 10,
                "responsibilities": 10,
                "education": 5,
                "certifications": 5,
                "preferred_qualifications": 10,
                "keywords": 30,
            },
        )
        job = make_job(
            r("r1", "Rust"), r("r2", "Elixir"), r("r3", "Python"), r("r4", "Django", classification="preferred"),
            keywords=("Python", "Django"),
        )  # fmt: skip
        report = run(job, config=config)
        assert report.match_score == 59
        assert report.score_cap
        assert "more than half" in report.score_cap

    def test_missing_preferred_never_caps(self) -> None:
        report = run(make_job(r("r1", "Python"), r("r2", "Rust", classification="preferred")))
        assert report.score_cap is None

    def test_components_without_requirements_are_renormalised(self) -> None:
        report = run(make_job(r("r1", "Python")))
        weights = {c.key: c.effective_weight for c in report.components}
        assert weights["required_skills"] == 100
        assert sum(weights.values()) == pytest.approx(100)
        assert next(c for c in report.components if c.key == "education").score is None

    def test_formula_is_weighted_average_of_components(self) -> None:
        # Required skills 100 (35), preferred 0 (12), keywords 50 (10): (3500 + 0 + 500) / 57 = 70.18 -> 70
        job = make_job(r("r1", "Python"), r("r2", "Rust", classification="preferred"), keywords=("Python", "Haskell"))
        report = run(job)
        assert report.match_score == 70
        assert sum(c.contribution for c in report.components) == pytest.approx(70.18, abs=0.02)

    def test_importance_weights_within_a_component(self) -> None:
        high_missing = run(make_job(r("r1", "Rust", importance="high"), r("r2", "Python", importance="low")))
        low_missing = run(make_job(r("r1", "Rust", importance="low"), r("r2", "Python", importance="high")))
        assert low_missing.match_score > high_missing.match_score

    def test_no_requirements_scores_zero_with_warning(self) -> None:
        report = run(make_job())
        assert report.match_score == 0
        assert report.warnings
        assert report.confidence.level == "low"

    def test_config_rejects_preferred_outweighing_required(self) -> None:
        with pytest.raises(ValueError, match="Required qualifications"):
            MatchingConfig(
                weights={
                    "required_skills": 5,
                    "experience": 5,
                    "responsibilities": 5,
                    "education": 5,
                    "certifications": 5,
                    "preferred_qualifications": 70,
                    "keywords": 5,
                }
            )


class TestExperience:
    def test_years_from_dated_roles_with_overlaps_merged(self) -> None:
        experience = [
            role("Engineer", "A", "Jan 2020", "Present", "Python services"),
            role("Contractor", "B", "Jun 2021", "Dec 2022", "Python scripts"),  # overlaps role A
        ]
        report = run(
            make_job(r("r1", "6+ years Python", "experience", min_years=6)),
            resume=make_resume(experience=experience, summary=None),
        )
        item = result(report, "r1")
        assert item.candidate_years == pytest.approx(6.8)  # Jan 2020 - Nov 2026, overlap counted once
        assert item.status == "matched"

    def test_years_short_of_requirement_are_partial(self) -> None:
        experience = [role("Engineer", "A", "2023", "Present", "Python services")]
        item = result(
            run(
                make_job(r("r1", "5+ years Python", "experience", min_years=5)),
                resume=make_resume(experience=experience, summary=None),
            ),
            "r1",
        )
        assert item.status == "partial"
        assert item.candidate_years == pytest.approx(3.8)
        assert item.credit == pytest.approx(0.76)

    def test_only_roles_mentioning_the_domain_count(self) -> None:
        experience = [
            role("Engineer", "A", "2024", "Present", "Python services"),
            role("Engineer", "B", "2015", "2024", "Java services"),
        ]
        item = result(
            run(
                make_job(r("r1", "5+ years Python", "experience", min_years=5)),
                resume=make_resume(experience=experience, summary=None),
            ),
            "r1",
        )
        assert item.candidate_years == pytest.approx(2.8)

    def test_stated_years_in_resume_count_as_evidence(self) -> None:
        item = result(run(make_job(r("r1", "5+ years Python", "experience", min_years=5))), "r1")
        assert item.status == "matched"
        assert any(e.label == "Stated in resume" for e in item.evidence)

    def test_as_of_date_affects_present_roles_deterministically(self) -> None:
        resume = make_resume(experience=[role("Engineer", "A", "Jan 2022", "Present", "Python")], summary=None)
        job = make_job(r("r1", "5+ years", "experience", min_years=5))
        structured, text = resume
        early = match_resume_to_job(structured, text, job, AVAILABLE, as_of=date(2025, 1, 1))
        late = match_resume_to_job(structured, text, job, AVAILABLE, as_of=date(2027, 1, 1))
        assert result(early, "r1").candidate_years < result(late, "r1").candidate_years

    def test_skill_without_dated_usage_is_unverified(self) -> None:
        resume = make_resume(experience=[], summary=None, skills=("Python",))
        item = result(run(make_job(r("r1", "5+ years Python", "experience", min_years=5)), resume=resume), "r1")
        assert item.status == "partial"
        assert item.credit == pytest.approx(0.35)
        assert "cannot be verified" in item.explanation

    def test_no_evidence_is_missing_and_never_invented(self) -> None:
        resume = make_resume(experience=[], summary=None, skills=())
        item = result(run(make_job(r("r1", "5+ years Scala", "experience", min_years=5)), resume=resume), "r1")
        assert item.status == "missing"
        assert item.candidate_years is None

    def test_responsibility_alignment_by_wording(self) -> None:
        job = make_job(
            r("r1", "Maintain PostgreSQL data pipelines", "responsibility"),
            r("r2", "Negotiate vendor contracts", "responsibility"),
        )
        report = run(job)
        assert result(report, "r1").status == "matched"
        assert result(report, "r2").status == "missing"
        assert report.experience.responsibility_alignment == 50

    def test_responsibility_semantic_similarity_is_partial(self) -> None:
        signals = SemanticSignals(
            status="available",
            text_pairs={"r1": SemanticPair(resume_text="Built Django REST services in Python.", similarity=0.9)},
        )
        item = result(run(make_job(r("r1", "Own API platform", "responsibility")), signals=signals), "r1")
        assert (item.status, item.match_type, item.credit) == ("partial", "semantic_text", 0.6)

    def test_seniority_alignment(self) -> None:
        job = make_job(r("r1", "Python"))
        job.info.title = tf("Staff Engineer")
        report = run(job)
        assert report.experience.seniority.status == "below"
        job.info.title = tf("Backend Engineer")
        assert run(job).experience.seniority.status == "unknown"


class TestQualifications:
    def test_degree_level_and_field_met(self) -> None:
        req = r(
            "r1", "Bachelor's degree", "education", evidence="Bachelor's degree in Computer Science or related field."
        )
        assert result(run(make_job(req)), "r1").status == "matched"

    def test_field_mismatch_is_partial(self) -> None:
        req = r("r1", "Bachelor's degree", "education", evidence="Bachelor's degree in Mechanical Engineering.")
        item = result(run(make_job(req)), "r1")
        assert (item.status, item.credit) == ("partial", 0.5)

    def test_lower_level_is_partial(self) -> None:
        req = r("r1", "Master's degree", "education", evidence="Master's degree in Computer Science.")
        item = result(run(make_job(req)), "r1")
        assert (item.status, item.credit) == ("partial", 0.25)

    def test_no_education_is_missing(self) -> None:
        req = r("r1", "Bachelor's degree", "education")
        assert result(run(make_job(req), resume=make_resume(education=[])), "r1").status == "missing"

    def test_certification_exact_related_and_missing(self) -> None:
        resume = make_resume(certifications=("AWS Certified Solutions Architect - Associate",))
        job = make_job(
            r("r1", "AWS Certified Solutions Architect", "certification"),
            r("r2", "AWS Certified Data Engineer", "certification"),
            r("r3", "CKA", "certification"),
        )
        report = run(job, resume=resume)
        assert result(report, "r1").status == "matched"
        assert result(report, "r2").status == "related"
        assert result(report, "r3").status == "missing"
        assert [c.name for c in report.qualifications.certifications_missing] == [
            "AWS Certified Data Engineer",
            "CKA",
        ]


class TestReportIntegrity:
    def test_identical_inputs_produce_identical_reports(self) -> None:
        job = make_job(
            r("r1", "FastAPI"),
            r("r2", "5+ years Python", "experience", min_years=5),
            r("r3", "Terraform", classification="preferred"),
            r("r4", "Bachelor's degree", "education", evidence="Bachelor's degree in Computer Science."),
            keywords=("Python", "Terraform"),
        )
        first, second = run(job), run(job)
        assert first.model_dump() == second.model_dump()

    def test_every_non_missing_result_has_evidence_and_every_result_an_explanation(self) -> None:
        job = make_job(r("r1", "FastAPI"), r("r2", "Rust"), r("r3", "Django"), r("r4", "Leadership", "soft_skill"))
        for item in run(job).requirements:
            assert item.explanation
            if item.status != "missing":
                assert item.evidence

    def test_recommendations_are_grounded_and_ranked(self) -> None:
        job = make_job(
            r("r1", "Rust", importance="high", evidence="Must have Rust."),
            r("r2", "FastAPI"),
            keywords=("Haskell",),
        )
        recs = run(job).recommendations
        assert recs.top[0].requirement_id == "r1"
        assert "Must have Rust." in recs.top[0].message
        assert "rather than claim" in recs.top[0].message
        assert "Rust" in recs.missing_evidence
        assert any("FastAPI" in item for item in recs.present_better)
        assert all(a.impact >= b.impact for a, b in zip(recs.top, recs.top[1:], strict=False))

    def test_methodology_is_reported(self) -> None:
        report = run(make_job(r("r1", "Python")))
        assert report.methodology.version == "job-match/1"
        assert sum(report.methodology.weights.values()) == 100
        assert "never supplies a number" in report.methodology.notes[0]
