"""Fictional resumes for export quality checks: a graduate resume, a long multi-page resume and an edge-case
resume (long unbroken strings, non-ASCII names, symbols that often break in PDFs and Word).

Used by the export tests and by ``scripts/render_export_samples.py``, which writes every template in both
formats for manual inspection in Word and PDF viewers. All people, employers and institutions are invented.
"""

from __future__ import annotations

from app.schemas.rewrite import (
    DocBullet,
    DocCertification,
    DocContact,
    DocEducation,
    DocExperience,
    DocLanguage,
    DocLink,
    DocProject,
    ResumeDocument,
)
from tests.fixtures.rewrite import sample_document


def graduate_document() -> ResumeDocument:
    return ResumeDocument(
        contact=DocContact(
            name="Alex Rivera",
            email="alex.rivera@example.com",
            phone="+44 7700 900123",
            location="Leeds, UK",
            links=[DocLink(kind="github", url="https://github.com/alex-rivera-example")],
        ),
        summary="Computer science graduate with internship experience in data engineering and a final-year project "
        "on accessible web interfaces.",
        education=[
            DocEducation(
                id="edu-1",
                institution="Northbridge University",
                qualification="BSc (Hons)",
                field_of_study="Computer Science",
                start_date="2022",
                end_date="2025",
                grade="First-class honours",
                coursework=["Algorithms and Data Structures", "Databases", "Human-Computer Interaction", "Networks"],
            )
        ],
        projects=[
            DocProject(
                id="proj-1",
                name="Accessible timetable planner (final-year project)",
                description="Built a timetable planner tested with screen-reader users; documented the accessibility "
                "audit and fixes.",
                technologies=["TypeScript", "React", "PostgreSQL"],
            ),
            DocProject(
                id="proj-2",
                name="Course reviews API",
                description="REST API for anonymous course reviews with rate limiting and moderation queues.",
                technologies=["Python", "FastAPI", "Docker"],
            ),
        ],
        experience=[
            DocExperience(
                id="exp-1",
                title="Data Engineering Intern",
                employer="Harbourline Logistics",
                location="Leeds",
                start_date="Jun 2024",
                end_date="Sep 2024",
                bullets=[
                    DocBullet(id="exp-1-b1", text="Automated a weekly shipment report that was previously compiled by "
                              "hand.", source_ids=["exp-1-b1"]),
                    DocBullet(id="exp-1-b2", text="Wrote data-quality checks for the warehouse ingestion pipeline.",
                              source_ids=["exp-1-b2"]),
                ],
            ),
            DocExperience(
                id="exp-2",
                title="Student Ambassador",
                employer="Northbridge University",
                start_date="2023",
                end_date="2025",
                bullets=[DocBullet(id="exp-2-b1", text="Led campus tours for prospective students.",
                                   source_ids=["exp-2-b1"])],
            ),
        ],
        technical_skills=["Python", "TypeScript", "React", "SQL", "PostgreSQL", "FastAPI", "Docker", "Git"],
        soft_skills=["Communication", "Teamwork"],
        certifications=[DocCertification(id="cert-1", name="AWS Certified Cloud Practitioner", issuer="Amazon Web "
                                          "Services", date="2025")],
        languages=[DocLanguage(name="English", proficiency="Native"), DocLanguage(name="Spanish",
                                                                                   proficiency="Conversational")],
    )  # fmt: skip


def long_document(roles: int = 6, bullets_per_role: int = 9) -> ResumeDocument:
    """A resume that spans several pages: many roles, long wrapping bullets and projects."""

    document = sample_document()
    long_text = (
        "Coordinated the migration of internal reporting services to a shared deployment platform, writing the "
        "runbooks, pairing with each owning team and retiring the legacy cron hosts once traffic had moved over "
        "(entry {n})."
    )
    document.experience = [
        DocExperience(
            id=f"exp-{r}",
            title=f"Software Engineer {r}",
            employer=f"Example Employer {r}",
            location="Remote",
            start_date=f"{2010 + r}",
            end_date=f"{2011 + r}",
            bullets=[
                DocBullet(id=f"exp-{r}-b{b}", text=long_text.format(n=f"{r}.{b}"), source_ids=[])
                for b in range(1, bullets_per_role + 1)
            ],
        )
        for r in range(1, roles + 1)
    ]
    document.projects = [
        DocProject(
            id=f"proj-{p}",
            name=f"Internal tooling project {p}",
            description="A command-line tool and dashboard for tracking deployment health across services. " * 3,
            technologies=["Python", "PostgreSQL", "Docker"],
        )
        for p in range(1, 4)
    ]
    return document


def edge_case_document() -> ResumeDocument:
    """Non-ASCII names, symbols, a very long unbroken URL-like token and characters that commonly break."""

    document = sample_document()
    document.contact.name = "Zoë Ñúñez-O'Brien"
    document.contact.links = [
        DocLink(kind="website", url="https://example.com/" + "very-long-path-segment-" * 6 + "end"),
    ]
    document.summary = (
        "Engineer — 6 years’ experience with C++, C#, .NET & Node.js; “quotes”, en–dash, ±5 ms, 100 °C, €2,000, "
        "naïve café résumé, 日本語 and Ελληνικά."
    )
    document.experience[0].bullets.append(
        DocBullet(
            id="edge-b1",
            text="Unbroken token: " + "a1b2c3d4e5" * 14 + " followed by normal wrapping words to finish the line.",
            source_ids=[],
        )
    )
    return document


SAMPLES = {
    "standard": sample_document,
    "graduate": graduate_document,
    "long": long_document,
    "edge-cases": edge_case_document,
}
