"""Skill lexicon: aliases are exact, families are related-only, ambiguous words need explicit context."""

from __future__ import annotations

import pytest

from app.services.matching import skills


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("k8s", "kubernetes"),
        ("Postgres", "postgresql"),
        ("golang", "go"),
        ("Node.js", "node.js"),
        ("Python 3.12", "python"),
    ],
)
def test_aliases_resolve_to_canonical(alias: str, canonical: str) -> None:
    assert skills.canonical(alias) == canonical


def test_unknown_terms_are_normalised_not_dropped() -> None:
    assert skills.canonical("  Event Sourcing ") == "event sourcing"


def test_family_members_are_related_but_never_the_same_skill() -> None:
    assert skills.same_family("FastAPI", "Django")
    assert skills.same_family("AWS", "GCP")
    assert not skills.same_family("Django", "Django")
    assert not skills.same_family("Python", "Java")  # languages deliberately have no family
    assert not skills.same_family("FastAPI", "Unknown Framework")


@pytest.mark.parametrize(
    ("text", "term", "expected"),
    [
        ("built services in c++ and python", "C++", True),
        ("deployed on k8s clusters", "Kubernetes", True),
        ("ready to go live next week", "Go", False),  # ambiguous: not matched in free text
        ("wrote golang microservices", "Go", True),  # an unambiguous alias still counts
        ("the rest of the team", "REST", False),
        ("designed restful apis", "REST", True),
        ("javascript developer", "Java", False),  # word boundaries
    ],
)
def test_mentions(text: str, term: str, expected: bool) -> None:
    assert skills.mentions(text, term) is expected


def test_scan_skips_ambiguous_entries() -> None:
    found = {entry.canonical for entry in skills.scan("we go fast with python and docker")}
    assert found == {"Python", "Docker"}
