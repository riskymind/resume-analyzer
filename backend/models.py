"""Pydantic request/response schemas shared across backend routes."""

from pydantic import BaseModel


class PingGeminiResponse(BaseModel):
    """Response returned by the Gemini smoke-test endpoint."""

    prompt: str
    response: str
