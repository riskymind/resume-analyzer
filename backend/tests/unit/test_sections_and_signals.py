"""Section detection and deterministic signals (contact details, dates, metrics)."""

from __future__ import annotations

import pytest

from app.parsing.normalize import normalize_text
from app.parsing.sections import classify_heading, detect_sections
from app.parsing.signals import (
    date_style,
    find_emails,
    find_links,
    find_metrics,
    find_phones,
    guess_name,
    is_present,
    parse_date,
)
from tests.fixtures.documents import SAMPLE_RESUME_MD


class TestSections:
    @pytest.mark.parametrize(
        ("line", "kind"),
        [
            ("Work Experience", "experience"),
            ("PROFESSIONAL EXPERIENCE", "experience"),
            ("## Employment History", "experience"),
            ("Education:", "education"),
            ("**Technical Skills**", "skills"),
            ("Core Competencies", "skills"),
            ("Licenses & Certifications", "certifications"),
            ("Profile", "summary"),
            ("Awards and Honours", "achievements"),
            ("Languages", "languages"),
            ("## Volunteering stuff", "other"),
        ],
    )
    def test_heading_aliases(self, line: str, kind: str) -> None:
        heading = classify_heading(line)
        assert heading is not None
        assert heading[0] == kind

    @pytest.mark.parametrize(
        "line",
        [
            "SENIOR SOFTWARE ENGINEER",  # caps job title, not a section
            "# Jane Doe",  # level-1 heading is the name
            "### Backend Engineer - Acme",  # entry heading
            "- Skills",  # bullet
            "I improved our education programme.",  # sentence
            "jane@example.com",
        ],
    )
    def test_non_headings(self, line: str) -> None:
        assert classify_heading(line) is None

    def test_sample_layout(self) -> None:
        layout = detect_sections(normalize_text(SAMPLE_RESUME_MD))
        assert [section.kind for section in layout.sections] == ["summary", "experience", "education", "skills"]
        assert layout.header_lines[0] == "# Jane Doe"
        assert "Acme Corp" in layout.text_of("experience")
        assert layout.has("skills")
        assert not layout.has("projects")

    def test_entry_subheadings_do_not_split_experience(self) -> None:
        text = "## Experience\n## Lead Engineer at Initech\n- Built things\n## Education\nBSc"
        layout = detect_sections(text)
        assert [s.kind for s in layout.sections] == ["experience", "education"]
        assert "Lead Engineer at Initech" in layout.text_of("experience")

    def test_no_headings_means_everything_is_header(self) -> None:
        layout = detect_sections("Jane Doe\nSome text")
        assert layout.sections == []
        assert layout.header_text == "Jane Doe\nSome text"


class TestContact:
    def test_emails(self) -> None:
        assert find_emails("Mail jane.doe+cv@example.co.uk or JANE@EXAMPLE.COM") == [
            "jane.doe+cv@example.co.uk",
            "JANE@EXAMPLE.COM",
        ]

    @pytest.mark.parametrize("phone", ["+234 803 123 4567", "(555) 010-0199", "+44 20 7946 0958", "07946 095 812"])
    def test_phone_numbers(self, phone: str) -> None:
        assert find_phones(f"Call {phone} today") == [phone]

    @pytest.mark.parametrize("text", ["2018 - 2021", "2019–2020", "Jan 2018 - Mar 2020", "+1 555 0100"])
    def test_not_phone_numbers(self, text: str) -> None:
        assert find_phones(text) == []

    def test_links(self) -> None:
        text = "linkedin.com/in/jane-doe | https://github.com/janedoe | www.janedoe.dev"
        links = find_links(text, header_text=text)
        assert [(link.kind, link.url) for link in links] == [
            ("linkedin", "linkedin.com/in/jane-doe"),
            ("github", "https://github.com/janedoe"),
            ("website", "www.janedoe.dev"),
        ]

    def test_email_domain_is_not_a_website(self) -> None:
        assert find_links("jane@janedoe.dev", header_text="jane@janedoe.dev") == []

    @pytest.mark.parametrize(
        ("header", "name"),
        [
            (["# Jane Doe"], "Jane Doe"),
            (["María José García-López | Madrid"], "María José García-López"),
            (["jane@example.com", "Jane Doe"], None),  # only the first non-empty line is considered
            (["Curriculum Vitae 2024"], None),
            ([], None),
        ],
    )
    def test_name_guess(self, header: list[str], name: str | None) -> None:
        assert guess_name(header) == name


class TestDatesAndMetrics:
    @pytest.mark.parametrize(
        ("token", "style", "parsed"),
        [
            ("Jan 2020", "Mon YYYY", (2020, 1)),
            ("Sept. 2021", "Mon YYYY", (2021, 9)),
            ("January 2020", "Month YYYY", (2020, 1)),
            ("June 2022", "Month YYYY", (2022, 6)),
            ("03/2019", "MM/YYYY", (2019, 3)),
            ("2018", "YYYY", (2018, 0)),
            ("Present", None, None),
        ],
    )
    def test_dates(self, token: str, style: str | None, parsed: tuple[int, int] | None) -> None:
        assert date_style(token) == style
        assert parse_date(token) == parsed

    @pytest.mark.parametrize("token", ["Present", "current", "Now", "to date"])
    def test_present(self, token: str) -> None:
        assert is_present(token)

    @pytest.mark.parametrize(
        ("text", "metrics"),
        [
            ("Cut deploy time by 35%.", ["35%"]),
            ("Saved $1.2M annually", ["$1.2M"]),
            ("Made pipelines 3x faster", ["3x"]),
            ("Handled 2M requests per day", ["2M"]),
            ("Managed a team of 5 engineers", ["5"]),
            ("Served 1,200,000 users", ["1,200,000"]),
            ("Maintained pipelines since 2018.", []),
            ("Worked on the billing system", []),
        ],
    )
    def test_metrics(self, text: str, metrics: list[str]) -> None:
        assert find_metrics(text) == metrics
