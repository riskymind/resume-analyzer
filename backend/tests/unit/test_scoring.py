"""Deterministic resume quality scoring."""

from __future__ import annotations

import copy
import inspect
from typing import Any

import pytest

from app.parsing.files import ExtractedDocument
from app.parsing.normalize import normalize_text
from app.parsing.sections import detect_sections
from app.schemas.resume import AIResumeExtraction
from app.schemas.scoring import DimensionScore, QualityReport
from app.services.extraction import build_structured_resume
from app.services.scoring.config import DEFAULT_WEIGHTS, ScoringConfig
from app.services.scoring.engine import ScoringInput, reading_ease, score_resume
from tests.fixtures.documents import SAMPLE_EXTRACTION, SAMPLE_RESUME_MD

FULL_RESUME = """# Jane Doe
jane.doe@example.com | +1 555 010 0199 | linkedin.com/in/janedoe | Lagos, Nigeria

## Summary
Backend engineer with 6 years of experience designing Python and Go services for payments and logistics. \
Known for turning slow, fragile systems into fast, observable platforms and for mentoring engineers.

## Experience
### Senior Software Engineer, Acme Corp, Jan 2021 - Present
- Led migration of 40 services to Kubernetes, cutting deploy time by 35%.
- Built FastAPI services handling 2M requests per day with 99.95% uptime.
- Reduced cloud costs by $120k per year by right-sizing PostgreSQL clusters.
- Mentored 5 engineers through promotion to senior roles.

### Software Engineer, Initech, Mar 2018 - Dec 2020
- Designed event-driven billing pipelines processing 300k invoices monthly.
- Automated release checks, reducing failed deployments by 60%.
- Introduced contract testing across 12 Docker-based services.

### Junior Developer, Globex, Jul 2016 - Feb 2018
- Developed internal reporting tools in Python used by 200 analysts.
- Rewrote nightly batch jobs, shortening runtime from 6 hours to 40 minutes.
- Fixed 150 production defects while on the support rotation.

## Education
BSc Computer Science, State University, Sep 2014 - Jun 2018

## Projects
### Ledgerline
Open-source double-entry ledger library in Go used by three fintech startups; 1,400 GitHub stars.

## Skills
Python, Go, FastAPI, PostgreSQL, Docker, Kubernetes, AWS, Terraform

## Certifications
AWS Certified Solutions Architect - Associate, Amazon Web Services, 2022
"""

FULL_EXTRACTION: dict[str, Any] = {
    "name": {"value": "Jane Doe"},
    "location": {"value": "Lagos, Nigeria"},
    "summary": {
        "value": "Backend engineer with 6 years of experience designing Python and Go services for payments and "
        "logistics. Known for turning slow, fragile systems into fast, observable platforms and for mentoring "
        "engineers."
    },
    "experience": [
        {
            "title": {"value": "Senior Software Engineer"},
            "employer": {"value": "Acme Corp"},
            "start_date": {"value": "Jan 2021"},
            "end_date": {"value": "Present"},
            "bullets": [
                {
                    "text": "Led migration of 40 services to Kubernetes, cutting deploy time by 35%.",
                    "type": "achievement",
                },
                {
                    "text": "Built FastAPI services handling 2M requests per day with 99.95% uptime.",
                    "type": "achievement",
                },
                {
                    "text": "Reduced cloud costs by $120k per year by right-sizing PostgreSQL clusters.",
                    "type": "achievement",
                },
                {"text": "Mentored 5 engineers through promotion to senior roles.", "type": "achievement"},
            ],
        },
        {
            "title": {"value": "Software Engineer"},
            "employer": {"value": "Initech"},
            "start_date": {"value": "Mar 2018"},
            "end_date": {"value": "Dec 2020"},
            "bullets": [
                {
                    "text": "Designed event-driven billing pipelines processing 300k invoices monthly.",
                    "type": "achievement",
                },
                {"text": "Automated release checks, reducing failed deployments by 60%.", "type": "achievement"},
                {"text": "Introduced contract testing across 12 Docker-based services.", "type": "responsibility"},
            ],
        },
        {
            "title": {"value": "Junior Developer"},
            "employer": {"value": "Globex"},
            "start_date": {"value": "Jul 2016"},
            "end_date": {"value": "Feb 2018"},
            "bullets": [
                {"text": "Developed internal reporting tools in Python used by 200 analysts.", "type": "achievement"},
                {
                    "text": "Rewrote nightly batch jobs, shortening runtime from 6 hours to 40 minutes.",
                    "type": "achievement",
                },
                {"text": "Fixed 150 production defects while on the support rotation.", "type": "achievement"},
            ],
        },
    ],
    "projects": [
        {
            "name": {"value": "Ledgerline"},
            "description": {
                "value": "Open-source double-entry ledger library in Go used by three fintech startups; "
                "1,400 GitHub stars."
            },
            "technologies": ["Go"],
        }
    ],
    "certifications": [
        {
            "name": {"value": "AWS Certified Solutions Architect - Associate"},
            "issuer": {"value": "Amazon Web Services"},
            "date": {"value": "2022"},
        }
    ],
    "education": [
        {
            "institution": {"value": "State University"},
            "qualification": {"value": "BSc"},
            "field_of_study": {"value": "Computer Science"},
            "start_date": {"value": "Sep 2014"},
            "end_date": {"value": "Jun 2018"},
        }
    ],
    "technical_skills": [
        {"name": n} for n in ("Python", "Go", "FastAPI", "PostgreSQL", "Docker", "Kubernetes", "AWS", "Terraform")
    ],
    "soft_skills": [{"name": "Mentoring", "evidence": "Mentored 5 engineers through promotion to senior roles."}],
}


def score(
    text: str, extraction: dict[str, Any], *, fmt: str = "pdf", config: ScoringConfig | None = None, **document: Any
) -> QualityReport:
    normalized = normalize_text(text)
    layout = detect_sections(normalized)
    structured = build_structured_resume(
        AIResumeExtraction.model_validate(extraction), text=normalized, layout=layout, provider_name="fake"
    )
    data = ScoringInput(
        document=ExtractedDocument(format=fmt, text=normalized, **document),  # type: ignore[arg-type]
        layout=layout,
        structured=structured,
    )
    return score_resume(data, config) if config else score_resume(data)


def dimension(report: QualityReport, key: str) -> DimensionScore:
    return next(d for d in report.dimensions if d.key == key)


def codes(report: QualityReport, key: str) -> set[str]:
    return {d.code for d in dimension(report, key).deductions}


class TestConfig:
    def test_default_weights_sum_to_100(self) -> None:
        assert sum(DEFAULT_WEIGHTS.values()) == 100

    def test_weights_must_sum_to_100(self) -> None:
        with pytest.raises(ValueError, match="sum to 100"):
            ScoringConfig(weights={**DEFAULT_WEIGHTS, "contact": 50})

    def test_weights_must_cover_every_dimension(self) -> None:
        weights = dict(DEFAULT_WEIGHTS)
        weights.pop("readability")
        with pytest.raises(ValueError, match="exactly"):
            ScoringConfig(weights=weights)

    @pytest.mark.parametrize(
        ("value", "label"),
        [
            (100, "Excellent"),
            (90, "Excellent"),
            (89, "Strong"),
            (75, "Strong"),
            (74, "Fair"),
            (60, "Fair"),
            (59, "Needs work"),
        ],
    )
    def test_label_bands(self, value: int, label: str) -> None:
        assert ScoringConfig().label_for(value) == label


class TestArithmetic:
    def test_overall_is_the_weighted_average_of_dimensions(self) -> None:
        report = score(FULL_RESUME, FULL_EXTRACTION)
        assert report.score_cap is None
        exact = sum(d.weight * d.score for d in report.dimensions) / 100
        assert report.overall_score == int(exact + 0.5)
        assert sum(d.weight for d in report.dimensions) == 100
        for d in report.dimensions:
            assert d.score == max(0, 100 - sum(x.points for x in d.deductions))
            assert d.contribution == round(d.weight * d.score / 100, 2)

    def test_custom_weights_change_only_the_weighting(self) -> None:
        base = score(FULL_RESUME, FULL_EXTRACTION)
        weights = {**DEFAULT_WEIGHTS, "readability": 0, "experience": 30}
        custom = score(FULL_RESUME, FULL_EXTRACTION, config=ScoringConfig(version="test/1", weights=weights))
        assert [d.score for d in custom.dimensions] == [d.score for d in base.dimensions]
        assert custom.scoring_version == "test/1"
        assert custom.overall_score == int(sum(weights[d.key] * d.score for d in custom.dimensions) / 100 + 0.5)

    def test_ats_score_is_100_minus_failed_checks(self) -> None:
        report = score(SAMPLE_RESUME_MD, SAMPLE_EXTRACTION, fmt="markdown")
        assert report.ats_score == 100 - sum(c.points for c in report.ats_checks if not c.passed)

    def test_recommendations_ranked_by_impact(self) -> None:
        report = score(SAMPLE_RESUME_MD, SAMPLE_EXTRACTION)
        impacts = [r.impact for r in report.recommendations]
        assert impacts == sorted(impacts, reverse=True)
        assert report.weaknesses == [r.message for r in report.recommendations[:5]]


class TestConsistency:
    def test_identical_input_gives_identical_report(self) -> None:
        reports = {score(FULL_RESUME, FULL_EXTRACTION).model_dump_json() for _ in range(5)}
        assert len(reports) == 1

    def test_item_order_from_the_model_does_not_change_the_score(self) -> None:
        shuffled = copy.deepcopy(FULL_EXTRACTION)
        shuffled["technical_skills"].reverse()
        shuffled["soft_skills"] = []
        a = score(FULL_RESUME, FULL_EXTRACTION)
        b = score(FULL_RESUME, shuffled)
        assert a.overall_score == b.overall_score

    def test_scoring_has_no_job_description_input(self) -> None:
        """Quality is job-independent by construction: nothing about a target job reaches the scorer."""

        assert list(inspect.signature(score_resume).parameters) == ["data", "config"]
        assert set(ScoringInput.__dataclass_fields__) == {"document", "layout", "structured"}

    def test_adding_a_real_metric_never_lowers_the_score(self) -> None:
        text = SAMPLE_RESUME_MD.replace(
            "Maintained PostgreSQL data pipelines.", "Maintained 14 PostgreSQL data pipelines."
        )
        extraction: dict[str, Any] = copy.deepcopy(SAMPLE_EXTRACTION)
        extraction["experience"][1]["bullets"][0]["text"] = "Maintained 14 PostgreSQL data pipelines."
        before = score(SAMPLE_RESUME_MD, SAMPLE_EXTRACTION)
        after = score(text, extraction)
        assert dimension(after, "achievements").score >= dimension(before, "achievements").score
        assert after.overall_score >= before.overall_score


class TestRules:
    def test_strong_resume_scores_highly_with_specific_strengths(self) -> None:
        report = score(FULL_RESUME, FULL_EXTRACTION)
        assert report.overall_score >= 90
        assert report.label == "Excellent"
        assert report.ats_score == 100
        assert report.missing_information == []
        assert any("Quantified result" in s for s in report.strengths)

    def test_contact_deductions(self) -> None:
        text = "# Jane Doe\n\n## Experience\n- Built things"
        report = score(text, {"name": {"value": "Jane Doe"}})
        assert codes(report, "contact") == {
            "contact.email_missing",
            "contact.phone_missing",
            "contact.links_missing",
            "contact.location_missing",
        }
        assert dimension(report, "contact").score == 100 - 40 - 20 - 10 - 10
        assert {"Email address", "Phone number", "Location"} <= set(report.missing_information)

    def test_missing_summary(self) -> None:
        text = SAMPLE_RESUME_MD.replace(
            "## Summary\nBackend engineer with 6 years of experience building Python APIs.\n", ""
        )
        report = score(text, {**SAMPLE_EXTRACTION, "summary": {"value": None}})
        assert dimension(report, "summary").score == 40
        assert "Professional summary" in report.missing_information

    def test_summary_buzzwords_and_first_person(self) -> None:
        summary = (
            "I am a hard-working, results-driven team player and I love my job. I am passionate about "
            "delivering value for every stakeholder in a dynamic environment every single day."
        )
        text = SAMPLE_RESUME_MD.replace("Backend engineer with 6 years of experience building Python APIs.", summary)
        report = score(text, {**SAMPLE_EXTRACTION, "summary": {"value": summary}})
        assert {"summary.first_person", "summary.buzzwords", "summary.generic"} <= codes(report, "summary")

    def test_weak_duty_phrases_and_missing_action_verbs(self) -> None:
        bullets = ["Responsible for the billing system.", "Worked on the API layer.", "Duties included code review."]
        text = "# Jane Doe\n## Experience\n### Engineer, Initech, 2019 - 2021\n" + "\n".join(f"- {b}" for b in bullets)
        extraction = {
            "experience": [
                {
                    "title": {"value": "Engineer"},
                    "employer": {"value": "Initech"},
                    "start_date": {"value": "2019"},
                    "end_date": {"value": "2021"},
                    "bullets": [{"text": b} for b in bullets],
                }
            ]
        }
        report = score(text, extraction)
        assert {"experience.action_verbs_poor", "experience.weak_phrases"} <= codes(report, "experience")
        assert "achievements.none" in codes(report, "achievements")
        assert report.metrics.action_verb_ratio == 0.0

    def test_no_quantified_bullets(self) -> None:
        bullets = ["Built the billing service.", "Improved test coverage.", "Led code reviews.", "Designed the API."]
        text = "# Jane\n## Experience\n### Engineer, Initech, 2019 - 2021\n" + "\n".join(f"- {b}" for b in bullets)
        extraction = {
            "experience": [
                {
                    "title": {"value": "Engineer"},
                    "employer": {"value": "Initech"},
                    "start_date": {"value": "2019"},
                    "bullets": [{"text": b} for b in bullets],
                }
            ]
        }
        report = score(text, extraction)
        quantified = next(
            d for d in dimension(report, "achievements").deductions if d.code == "achievements.quantified"
        )
        assert quantified.points == 70
        assert "Do not estimate numbers" in quantified.recommendation

    def test_graduate_with_projects_is_not_scored_as_zero_experience(self) -> None:
        text = "# Sam Lee\n## Projects\nTaskBoard - a React app\n## Education\nBSc, State University, 2024"
        with_projects = score(text, {"projects": [{"name": {"value": "TaskBoard"}}]})
        without = score(text, {})
        assert dimension(with_projects, "experience").score == 50
        assert dimension(without, "experience").score == 0

    def test_mixed_date_formats(self) -> None:
        extraction = copy.deepcopy(FULL_EXTRACTION)
        text = FULL_RESUME.replace("Mar 2018 - Dec 2020", "03/2018 - 2020")
        extraction["experience"][1]["start_date"] = {"value": "03/2018"}
        extraction["experience"][1]["end_date"] = {"value": "2020"}
        report = score(text, extraction)
        assert "formatting.date_styles" in codes(report, "formatting")

    def test_reverse_chronology_and_reversed_ranges(self) -> None:
        extraction = copy.deepcopy(FULL_EXTRACTION)
        extraction["experience"].reverse()
        report = score(FULL_RESUME, extraction)
        assert "experience.order" in codes(report, "experience")

    def test_unevidenced_skills(self) -> None:
        skills = ["Rust", "Haskell", "Elixir", "Scala", "OCaml", "Erlang"]
        text = FULL_RESUME.replace(
            "Python, Go, FastAPI, PostgreSQL, Docker, Kubernetes, AWS, Terraform", ", ".join(skills)
        )
        report = score(text, {**FULL_EXTRACTION, "technical_skills": [{"name": s} for s in skills]})
        assert "skills.unevidenced" in codes(report, "skills")

    def test_very_short_resume_is_capped_with_explanation(self) -> None:
        report = score(SAMPLE_RESUME_MD, SAMPLE_EXTRACTION)
        assert report.metrics.word_count < 150
        assert report.overall_score == 70
        assert report.score_cap is not None
        assert "only" in report.score_cap
        uncapped = sum(d.weight * d.score for d in report.dimensions) / 100
        assert uncapped > 70

    def test_full_resume_is_not_capped(self) -> None:
        assert score(FULL_RESUME, FULL_EXTRACTION).score_cap is None

    def test_length_bands(self) -> None:
        long_text = FULL_RESUME + "\n## Projects\n" + ("Built a thing that did useful work for people. " * 300)
        assert "structure.too_long" in codes(score(long_text, FULL_EXTRACTION), "structure")
        assert "structure.too_short" in codes(score(SAMPLE_RESUME_MD, SAMPLE_EXTRACTION), "structure")

    def test_reading_ease(self) -> None:
        assert reading_ease([]) is None
        easy = reading_ease(["We built a fast app.", "It ran well."])
        hard = reading_ease(["Institutionalised multidisciplinary interoperability considerations organisationally."])
        assert easy is not None
        assert hard is not None
        assert easy > hard


class TestAts:
    def failed(self, report: QualityReport) -> set[str]:
        return {c.code for c in report.ats_checks if not c.passed}

    def test_markdown_format_flagged(self) -> None:
        assert "ats.file_format" in self.failed(score(FULL_RESUME, FULL_EXTRACTION, fmt="markdown"))

    def test_docx_tables_flagged(self) -> None:
        assert "ats.tables" in self.failed(score(FULL_RESUME, FULL_EXTRACTION, fmt="docx", table_count=2))

    def test_contact_only_in_page_header_flagged(self) -> None:
        report = score(
            FULL_RESUME,
            FULL_EXTRACTION,
            fmt="docx",
            page_header_text="jane.doe@example.com",
            body_text="Experience without contact details",
        )
        assert "ats.contact_in_body" in self.failed(report)

    def test_image_pages_flagged(self) -> None:
        assert "ats.image_pages" in self.failed(score(FULL_RESUME, FULL_EXTRACTION, pages_without_text=[2]))

    def test_icons_flagged(self) -> None:
        text = FULL_RESUME.replace("jane.doe@example.com", "\U0001f4e7 jane.doe@example.com ☎ ✉ ★ ☆ ♥ ♫")
        assert "ats.symbols" in self.failed(score(text, FULL_EXTRACTION))

    def test_disclaimer_present(self) -> None:
        assert "does not predict or guarantee" in score(FULL_RESUME, FULL_EXTRACTION).disclaimer
