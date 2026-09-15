"""Wrapper around the Gemini API. All prompt construction and SDK calls for
this project should live here, not inline in route handlers.
"""

import os

import google.generativeai as genai

GEMINI_MODEL = "gemini-1.5-flash"


class GeminiClientError(Exception):
    """Raised when a Gemini API call fails or is misconfigured."""


def _get_model() -> genai.GenerativeModel:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiClientError("GEMINI_API_KEY is not set")

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(GEMINI_MODEL)


def ping_gemini() -> tuple[str, str]:
    """Send a hardcoded smoke-test prompt to Gemini and return (prompt, response text).

    Used to confirm frontend -> backend -> Gemini wiring end to end before any
    real analysis feature work begins.
    """

    prompt = "Reply with a short, friendly confirmation that this connection works."

    try:
        model = _get_model()
        result = model.generate_content(prompt)
        text = (result.text or "").strip()
    except GeminiClientError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any SDK/network failure uniformly
        raise GeminiClientError(f"Gemini API call failed: {exc}") from exc

    if not text:
        raise GeminiClientError("Gemini API returned an empty response")

    return prompt, text
