"""Wrapper around the Gemini API. All prompt construction and SDK calls for
this project should live here, not inline in route handlers.
"""

import json
import os

import google.generativeai as genai

from models import AnalysisResult, Recommendations

GEMINI_MODEL = "gemini-3.6-flash"

# Fixed score -> tier label thresholds, checked from highest to lowest. The
# label is derived here rather than asked of Gemini so it can never disagree
# with the numeric score.
_SCORE_THRESHOLDS = (
    (80, "Strong Match"),
    (60, "Good Match"),
    (40, "Fair Match"),
    (0, "Weak Match"),
)

_ANALYSIS_PROMPT_TEMPLATE = """You are an expert technical recruiter. Compare the RESUME against the \
JOB DESCRIPTION below and assess how well the candidate fits the role.

Respond with ONLY a single JSON object (no markdown fences, no commentary) matching exactly this shape:
{{
  "score": <integer 0-100, how well the resume matches the job description>,
  "recommendations": {{
    "missing_keywords": [<strings: important JD keywords/skills absent from the resume>],
    "phrasing_suggestions": [<strings: concrete phrasing/wording improvements for the resume>],
    "skill_gaps": [<strings: skills/experience the JD wants that the candidate appears to lack>],
    "formatting_notes": [<strings: resume formatting/structure issues, if any>]
  }}
}}

Each list may be empty if there is nothing to report, but must always be present.

RESUME:
{resume_text}

JOB DESCRIPTION:
{jd_text}
"""


class GeminiClientError(Exception):
    """Raised when a Gemini API call fails or is misconfigured."""


def _get_model() -> genai.GenerativeModel:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiClientError("GEMINI_API_KEY is not set")

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(GEMINI_MODEL)


def _score_label(score: int) -> str:
    """Map a 0-100 fitment score to a fixed tier label."""

    for threshold, label in _SCORE_THRESHOLDS:
        if score >= threshold:
            return label
    return "Weak Match"  # unreachable given the 0 floor above, kept for safety


def analyze_resume(resume_text: str, jd_text: str) -> AnalysisResult:
    """Send resume + job description text to Gemini and return a structured result.

    Raises GeminiClientError on misconfiguration, an API/network failure, or a
    response that doesn't match the expected JSON shape.
    """

    prompt = _ANALYSIS_PROMPT_TEMPLATE.format(resume_text=resume_text, jd_text=jd_text)

    try:
        model = _get_model()
        result = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )
        raw_text = (result.text or "").strip()
    except GeminiClientError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any SDK/network failure uniformly
        raise GeminiClientError(f"Gemini API call failed: {exc}") from exc

    if not raw_text:
        raise GeminiClientError("Gemini API returned an empty response")

    try:
        data = json.loads(raw_text)
        score = int(data["score"])
        recommendations = Recommendations(**data["recommendations"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise GeminiClientError(f"Gemini returned an unexpected response shape: {exc}") from exc

    if not 0 <= score <= 100:
        raise GeminiClientError(f"Gemini returned an out-of-range score: {score}")

    return AnalysisResult(score=score, score_label=_score_label(score), recommendations=recommendations)
