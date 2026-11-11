"""Job-matching configuration: weights, credits and thresholds in one versioned place.

Changing any value changes match scores, so bump ``version`` when you do. The
full configuration is stored in ``matching_configs`` and every match references
the version that produced it. Methodology: docs/job-matching-methodology.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.schemas.matching import ComponentKey

DEFAULT_COMPONENT_WEIGHTS: dict[ComponentKey, int] = {
    "required_skills": 35,
    "experience": 20,
    "responsibilities": 10,
    "education": 8,
    "certifications": 5,
    "preferred_qualifications": 12,
    "keywords": 10,
}

COMPONENT_LABELS: dict[ComponentKey, str] = {
    "required_skills": "Required skills",
    "experience": "Required experience",
    "responsibilities": "Responsibility alignment",
    "education": "Required education",
    "certifications": "Required certifications",
    "preferred_qualifications": "Preferred qualifications",
    "keywords": "Job keywords",
}


@dataclass(frozen=True)
class MatchingConfig:
    version: str = "job-match/1"
    weights: dict[ComponentKey, int] = field(default_factory=lambda: dict(DEFAULT_COMPONENT_WEIGHTS))
    importance_weights: dict[str, float] = field(default_factory=lambda: {"high": 1.5, "medium": 1.0, "low": 0.5})

    # Credits (share of a requirement's weight awarded)
    exact_credit: float = 1.0
    related_credit: float = 0.35  # related skill (lexicon family or embedding) - never equivalent
    years_unverified_credit: float = 0.35  # skill evidenced, but years with it cannot be verified
    text_partial_credit: float = 0.5  # some wording overlap with a resume bullet
    semantic_text_credit: float = 0.6  # bullet semantically similar to the requirement
    education_field_mismatch_credit: float = 0.5
    education_level_below_credit: float = 0.25

    # Thresholds
    semantic_related_threshold: float = 0.80  # skill name vs skill name cosine similarity
    semantic_text_threshold: float = 0.82  # requirement sentence vs resume bullet cosine similarity
    text_overlap_full: float = 0.6  # share of requirement content words found in one resume unit
    text_overlap_partial: float = 0.34

    # Caps: a missing mandatory requirement keeps the match below "Strong".
    missing_required_cap: int = 79
    majority_required_missing_cap: int = 59

    label_bands: tuple[tuple[int, str], ...] = (
        (80, "Strong Match"),
        (60, "Good Match"),
        (40, "Fair Match"),
        (0, "Weak Match"),
    )
    classifications: tuple[tuple[int, str], ...] = (
        (80, "The resume evidences most of what this job asks for."),
        (60, "The resume evidences many requirements, with some gaps."),
        (40, "The resume evidences some requirements; several important ones are not shown."),
        (0, "The resume shows little evidence for this job's requirements."),
    )

    def __post_init__(self) -> None:
        if set(self.weights) != set(DEFAULT_COMPONENT_WEIGHTS):
            raise ValueError(f"Matching weights must define exactly: {sorted(DEFAULT_COMPONENT_WEIGHTS)}")
        if any(weight < 0 for weight in self.weights.values()):
            raise ValueError("Matching weights must be non-negative.")
        if sum(self.weights.values()) != 100:
            raise ValueError(f"Matching weights must sum to 100 (got {sum(self.weights.values())}).")
        required_share = sum(w for k, w in self.weights.items() if k not in ("preferred_qualifications", "keywords"))
        if required_share <= self.weights["preferred_qualifications"]:
            raise ValueError("Required qualifications must carry more weight than preferred ones.")

    def label_for(self, score: int) -> str:
        return next(label for threshold, label in self.label_bands if score >= threshold)

    def classification_for(self, score: int) -> str:
        return next(text for threshold, text in self.classifications if score >= threshold)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["label_bands"] = [list(band) for band in self.label_bands]
        data["classifications"] = [list(item) for item in self.classifications]
        return data


DEFAULT_MATCHING_CONFIG = MatchingConfig()
