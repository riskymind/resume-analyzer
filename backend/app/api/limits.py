"""Shared AI usage limits (per user, stored in the database)."""

from __future__ import annotations

from app.core.config import Settings
from app.services.rate_limit import RateLimiter


def enforce_ai_limits(limiter: RateLimiter, settings: Settings, user_id: str) -> None:
    """Count one AI-backed operation for ``user_id``; raise 429 when over the per-minute or daily limit."""

    limiter.hit(
        "ai:minute",
        user_id,
        limit=settings.ai_max_requests_per_minute,
        window_seconds=60,
        message="You're sending analyses too quickly. Please wait a minute and try again.",
    )
    limiter.hit(
        "ai:day",
        user_id,
        limit=settings.ai_max_requests_per_day,
        window_seconds=24 * 3600,
        message="You've reached today's analysis limit. Please try again tomorrow.",
    )
