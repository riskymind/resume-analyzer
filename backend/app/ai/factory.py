"""Builds the configured AI provider from settings."""

from __future__ import annotations

from app.ai.base import AIProvider
from app.core.config import Settings


def build_ai_provider(settings: Settings) -> AIProvider | None:
    """Return the configured provider, or ``None`` when it has no credentials.

    A missing key is fatal in production (enforced by Settings) but allowed in
    development so the rest of the app can still be used.
    """

    if settings.ai_provider == "gemini":
        if settings.gemini_api_key is None:
            return None
        from app.ai.gemini import GeminiProvider

        return GeminiProvider(
            api_key=settings.gemini_api_key.get_secret_value(),
            model=settings.gemini_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            total_timeout_seconds=settings.ai_total_timeout_seconds,
            embedding_model=settings.gemini_embedding_model,
            embedding_dimensions=settings.embedding_dimensions,
        )
    raise ValueError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")
