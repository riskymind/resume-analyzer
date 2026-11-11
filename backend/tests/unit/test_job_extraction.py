"""Job description extraction: AI output is verified against the original text before it is trusted."""

from __future__ import annotations

from typing import Any

import pytest

from app.schemas.job import AIJobExtraction, StructuredJob
from app.services.job_extraction import build_structured_job, parse_min_years
from tests.fixtures.documents import SAMPLE_JD, SAMPLE_JOB_EXTRACTION

JD = """Senior Data Engineer - Initrode (Remote, Full-time)

About the role
You will build batch and streaming pipelines for our analytics platform.

Responsibilities:
- Design and operate Airflow pipelines feeding Snowflake.
- Partner with analysts to define data models.

Requirements:
- 4+ years of experience in data engineering.
- Strong SQL and Python.
- Experience with Kafka or RabbitMQ.
- Excellent communication with non-technical stakeholders.

Preferred qualifications:
- AWS Certified Data Engineer certification.
- Experience with dbt.

Python required, Scala is a plus.
Our stack also includes Docker.
"""


def req(
    name: str, category: str, evidence: str | None, classification: str = "required", **extra: Any
) -> dict[str, Any]:
    return {"name": name, "category": category, "classification": classification, "evidence": evidence, **extra}


def build(requirements: list[dict[str, Any]], text: str = JD, **fields: Any) -> StructuredJob:
    raw = AIJobExtraction.model_validate({"requirements": requirements, **fields})
    return build_structured_job(raw, text=text, provider_name="fake")


def by_name(job: StructuredJob) -> dict[str, Any]:
    return {r.name: r for r in job.requirements}


class TestEvidenceVerification:
    def test_verified_requirement_keeps_verbatim_evidence(self) -> None:
        job = build([req("SQL", "technical_skill", "Strong SQL and Python.")])
        sql = by_name(job)["SQL"]
        assert sql.status == "verified"
        assert sql.evidence == "Strong SQL and Python."
        assert sql.id == "r1"

    def test_requirement_not_in_text_is_discarded(self) -> None:
        job = build([req("Kubernetes", "technical_skill", "Experience with Kubernetes in production.")])
        assert "Kubernetes" not in by_name(job)
        assert job.extraction.removed_items == 1
        assert "discarded" in job.extraction.warnings[0]

    def test_skill_not_named_in_text_is_discarded_even_with_real_evidence(self) -> None:
        # The evidence sentence exists, but it does not name Terraform: the model cannot add typical skills.
        job = build([req("Terraform", "technical_skill", "Strong SQL and Python.")])
        assert "Terraform" not in by_name(job)

    def test_paraphrased_evidence_falls_back_to_the_sentence_naming_the_skill(self) -> None:
        job = build([req("dbt", "technical_skill", "dbt experience preferred")])  # not verbatim
        assert by_name(job)["dbt"].evidence == "- Experience with dbt."

    def test_soft_skill_may_be_named_differently_when_evidence_is_verbatim(self) -> None:
        job = build([req("Communication", "soft_skill", "Excellent communication with non-technical stakeholders.")])
        assert by_name(job)["Communication"].category == "soft_skill"

    def test_unknown_category_and_overlong_names_are_dropped(self) -> None:
        job = build([req("SQL", "vibes", "Strong SQL and Python."), req("x" * 200, "experience", "Strong SQL")])
        assert [r for r in job.requirements if r.status == "verified"] == []
        assert job.extraction.removed_items == 2

    def test_aliases_are_deduplicated(self) -> None:
        text = "Requirements: PostgreSQL (Postgres) experience."
        job = build([req("PostgreSQL", "technical_skill", text), req("Postgres", "technical_skill", text)], text=text)
        assert [r.name for r in job.requirements] == ["PostgreSQL"]

    def test_job_info_is_verified(self) -> None:
        job = build(
            [],
            title={"value": "Senior Data Engineer"},
            company={"value": "Initrode"},
            location={"value": "Mars Base"},
            seniority={"value": "Senior"},
        )
        assert job.info.title.value == "Senior Data Engineer"
        assert job.info.company.value == "Initrode"
        assert job.info.location.value is None  # invented
        assert job.info.seniority.value == "Senior"


class TestClassification:
    def test_heading_marks_items_preferred_even_if_model_says_required(self) -> None:
        job = build([req("dbt", "technical_skill", "- Experience with dbt.", classification="required")])
        dbt = by_name(job)["dbt"]
        assert (dbt.classification, dbt.classification_source) == ("preferred", "text")
        assert job.extraction.reclassified_items == 1

    def test_requirements_heading_marks_items_required(self) -> None:
        job = build(
            [req("Kafka", "technical_skill", "- Experience with Kafka or RabbitMQ.", classification="preferred")]
        )
        assert by_name(job)["Kafka"].classification == "required"

    def test_inline_cue_in_sentence(self) -> None:
        job = build([req("Terraform", "technical_skill", "Nice to have: Terraform, GCP.")], text=SAMPLE_JD)
        assert by_name(job)["Terraform"].classification == "preferred"

    def test_mixed_sentence_is_decided_per_clause(self) -> None:
        job = build(
            [
                req("Python", "technical_skill", "Python required, Scala is a plus.", classification="preferred"),
                req("Scala", "technical_skill", "Python required, Scala is a plus.", classification="required"),
            ]
        )
        names = by_name(job)
        assert names["Python"].classification == "required"
        assert names["Scala"].classification == "preferred"

    def test_ambiguous_text_keeps_model_classification(self) -> None:
        job = build([req("Airflow", "technical_skill", "- Design and operate Airflow pipelines feeding Snowflake.")])
        airflow = by_name(job)["Airflow"]
        assert airflow.classification_source in ("ai", "text")
        # Under "Responsibilities:" (a heading without a cue) the text does not decide.
        assert airflow.classification_source == "ai"


class TestYearsAndDetection:
    @pytest.mark.parametrize(
        ("text", "years"),
        [
            ("5+ years of Python", 5),
            ("3-5 years experience", 3),
            ("at least five years in fintech", 5),
            ("2 yrs", 2),
            ("A degree in Physics", None),
            ("Founded 120 years ago", None),
        ],
    )
    def test_parse_min_years(self, text: str, years: float | None) -> None:
        assert parse_min_years(text) == years

    def test_model_years_not_in_evidence_are_dropped(self) -> None:
        job = build(
            [
                req("Data engineering", "experience", "- 4+ years of experience in data engineering.", min_years=10),
                req("Stakeholders", "experience", "- Partner with analysts to define data models.", min_years=3),
            ]
        )
        names = by_name(job)
        assert names["Data engineering"].min_years == 4  # parsed from the text, not the model's 10
        assert names["Stakeholders"].min_years is None

    def test_lexicon_adds_missed_skills_as_preferred_unless_text_says_required(self) -> None:
        job = build([])
        detected = {r.name: r for r in job.requirements if r.status == "detected"}
        assert detected["Docker"].classification == "preferred"  # "Our stack also includes Docker."
        assert detected["Kafka"].classification == "required"  # under "Requirements:"
        assert detected["Docker"].importance == "low"
        assert job.extraction.detected_items == len(detected)

    def test_alternatives_are_grouped_conservatively(self) -> None:
        job = build_structured_job(
            AIJobExtraction.model_validate(SAMPLE_JOB_EXTRACTION), text=SAMPLE_JD, provider_name="fake"
        )
        names = by_name(job)
        assert names["FastAPI"].alternative_group is not None
        assert names["FastAPI"].alternative_group == names["Django"].alternative_group
        assert names["Python"].alternative_group is None  # "Python, FastAPI or Django": Python stays mandatory
        assert names["Terraform"].classification == "preferred"

    def test_keywords_must_appear_in_text(self) -> None:
        job = build([], keywords=[{"term": "Snowflake"}, {"term": "Blockchain"}])
        terms = [k.term for k in job.keywords]
        assert "Snowflake" in terms
        assert "Blockchain" not in terms
