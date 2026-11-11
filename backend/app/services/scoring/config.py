"""Scoring configuration: weights, thresholds and penalty sizes in one versioned place.

Changing any value changes scores, so bump ``version`` when you do; the
version is stored with every saved analysis. See docs/scoring-methodology.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.scoring import DimensionKey

DEFAULT_WEIGHTS: dict[DimensionKey, int] = {
    "contact": 10,
    "structure": 10,
    "summary": 10,
    "experience": 20,
    "achievements": 15,
    "skills": 10,
    "education": 5,
    "formatting": 10,
    "readability": 10,
}

DIMENSION_LABELS: dict[DimensionKey, str] = {
    "contact": "Contact information",
    "structure": "Structure and length",
    "summary": "Professional summary",
    "experience": "Experience descriptions",
    "achievements": "Achievements and impact",
    "skills": "Skills",
    "education": "Education",
    "formatting": "Formatting consistency",
    "readability": "Readability",
}


@dataclass(frozen=True)
class ScoringConfig:
    version: str = "resume-quality/1"
    weights: dict[DimensionKey, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    # Overall-score labels, checked from the top.
    label_bands: tuple[tuple[int, str], ...] = ((90, "Excellent"), (75, "Strong"), (60, "Fair"), (0, "Needs work"))

    # Length (words in the whole document)
    words_very_short: int = 150
    words_short: int = 250
    words_long: int = 1200
    words_very_long: int = 1800
    # A resume under words_very_short cannot score above this, however polished its few lines are.
    very_short_score_cap: int = 70

    # Summary
    summary_min_words: int = 20
    summary_max_words: int = 100

    # Experience bullets
    min_bullets_per_role: int = 2
    min_total_bullets: int = 4
    max_bullets_per_role: int = 8
    action_verb_ratio_good: float = 0.7
    action_verb_ratio_poor: float = 0.5
    bullet_words_max_avg: int = 35
    bullet_words_min_avg: int = 5

    # Quantified bullets (share of all experience bullets with a metric)
    quantified_bands: tuple[tuple[float, int], ...] = ((0.4, 0), (0.25, 15), (0.1, 35), (0.0001, 50), (0.0, 70))

    # Skills
    skills_few: int = 5
    skills_many: int = 40
    skills_evidenced_ratio_min: float = 0.3

    # Readability
    reading_ease_hard: float = 25.0
    reading_ease_very_hard: float = 10.0
    sentence_words_long: int = 25
    sentence_words_very_long: int = 30

    def __post_init__(self) -> None:
        if set(self.weights) != set(DEFAULT_WEIGHTS):
            raise ValueError(f"Scoring weights must define exactly: {sorted(DEFAULT_WEIGHTS)}")
        if any(weight < 0 for weight in self.weights.values()):
            raise ValueError("Scoring weights must be non-negative.")
        if sum(self.weights.values()) != 100:
            raise ValueError(f"Scoring weights must sum to 100 (got {sum(self.weights.values())}).")

    def label_for(self, score: int) -> str:
        for threshold, label in self.label_bands:
            if score >= threshold:
                return label
        return self.label_bands[-1][1]


DEFAULT_CONFIG = ScoringConfig()
