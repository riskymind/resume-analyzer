"""Smoke-test route confirming frontend -> backend -> Gemini wiring."""

from fastapi import APIRouter, HTTPException

from models import PingGeminiResponse
from services.gemini_client import GeminiClientError, ping_gemini

router = APIRouter()


@router.get("/ping-gemini", response_model=PingGeminiResponse)
def ping_gemini_endpoint() -> PingGeminiResponse:
    try:
        prompt, response_text = ping_gemini()
    except GeminiClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return PingGeminiResponse(prompt=prompt, response=response_text)
