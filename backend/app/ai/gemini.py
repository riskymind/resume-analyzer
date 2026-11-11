"""Gemini adapter (``google-genai`` SDK). The only module that imports the SDK.

Retries are done here rather than by the SDK so that one overall deadline
(``total_timeout_seconds``) bounds every call, back-off included (R3). Each call
logs its latency, attempt count, finish reason and token counts, never prompt or
response content (R4).
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx2
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.ai.base import AIProviderError

# google-genai sends requests through httpx2 by default and through httpx only when that is installed and selected
# (GOOGLE_GENAI_HTTP_CLIENT=httpx). The two are separate libraries whose exception classes are unrelated, so both
# are recognised; httpx is optional (it is not a production dependency).
try:
    import httpx
except ImportError:  # pragma: no cover - production images do not ship httpx
    httpx = None  # type: ignore[assignment]

_TRANSPORT_ERRORS: tuple[type[Exception], ...] = (httpx2.TransportError,) + (
    (httpx.TransportError,) if httpx is not None else ()
)
_TIMEOUT_ERRORS: tuple[type[Exception], ...] = (httpx2.TimeoutException,) + (
    (httpx.TimeoutException,) if httpx is not None else ()
)

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
# A retry is not started unless at least this much of the overall deadline is left.
_MIN_ATTEMPT_SECONDS = 3.0
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 8.0

ResponseT = TypeVar("ResponseT")


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        total_timeout_seconds: float = 90.0,
        embedding_model: str = "gemini-embedding-001",
        embedding_dimensions: int = 768,
    ) -> None:
        self.model = model
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.total_timeout_seconds = total_timeout_seconds
        # Seams for tests.
        self._clock: Callable[[], float] = time.monotonic
        self._sleep: Callable[[float], None] = time.sleep
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                # One attempt per SDK call; _call_with_retries owns retries and the deadline.
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    # ------------------------------------------------------------------ retries

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, genai_errors.APIError):
            return getattr(exc, "code", None) in _RETRYABLE_STATUS
        # Timeouts and connection failures.
        return isinstance(exc, _TRANSPORT_ERRORS)

    def _backoff(self, attempt: int) -> float:
        delay = min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
        return float(delay + random.uniform(0, delay / 2))  # noqa: S311 - jitter, not security

    def _call_with_retries(
        self, operation: str, call: Callable[[int], ResponseT], log_extra: dict[str, Any]
    ) -> tuple[ResponseT, int]:
        """Run ``call(timeout_ms)`` with retries inside one deadline. Returns the response and attempt count.

        Re-raises the last exception when attempts or time run out.
        """

        deadline = self._clock() + self.total_timeout_seconds
        attempt = 0
        while True:
            attempt += 1
            remaining = deadline - self._clock()
            timeout = min(self.timeout_seconds, remaining)
            try:
                return call(max(1, int(timeout * 1000))), attempt
            except Exception as exc:
                if not self._is_retryable(exc) or attempt > self.max_retries:
                    log_extra["attempts"] = attempt
                    raise
                delay = self._backoff(attempt)
                if deadline - self._clock() - delay < _MIN_ATTEMPT_SECONDS:
                    log_extra["attempts"] = attempt
                    logger.warning(
                        "ai_deadline_exhausted",
                        extra={**log_extra, "operation": operation, "total_timeout_s": self.total_timeout_seconds},
                    )
                    raise
                logger.info(
                    "ai_provider_retry",
                    extra={
                        **log_extra,
                        "operation": operation,
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                        "status": getattr(exc, "code", None),
                        "backoff_s": round(delay, 2),
                    },
                )
                self._sleep(delay)

    # ------------------------------------------------------------------ generation

    def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
        task: str = "generate",
    ) -> str:
        log_extra: dict[str, Any] = {"provider": self.name, "model": self.model, "task": task}

        def call(timeout_ms: int) -> types.GenerateContentResponse:
            config = types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=json_schema,
                max_output_tokens=max_output_tokens,
                temperature=0.2,
                http_options=types.HttpOptions(timeout=timeout_ms),
            )
            return self._client.models.generate_content(model=self.model, contents=prompt, config=config)

        started = self._clock()
        try:
            response, attempts = self._call_with_retries("generate", call, log_extra)
        except genai_errors.APIError as exc:
            status = getattr(exc, "code", None)
            logger.warning(
                "ai_provider_error",
                extra={**log_extra, "status": status, **_error_details(exc), **_elapsed(started, self._clock)},
            )
            if status == 429:
                raise AIProviderError(
                    "The AI provider is rate limiting requests. Try again shortly.", retryable=True
                ) from exc
            raise AIProviderError(
                f"The AI provider returned an error (status {status}).",
                retryable=status in _RETRYABLE_STATUS,
            ) from exc
        except _TIMEOUT_ERRORS as exc:
            logger.warning("ai_provider_timeout", extra={**log_extra, **_elapsed(started, self._clock)})
            raise AIProviderError("The AI provider timed out.", retryable=True) from exc
        except Exception as exc:
            logger.warning(
                "ai_provider_failure",
                extra={**log_extra, "error_type": type(exc).__name__, **_elapsed(started, self._clock)},
            )
            raise AIProviderError("The AI provider request failed.", retryable=True) from exc

        finish_reason = _finish_reason(response)
        usage = _usage(response)
        log_extra.update(
            attempts=attempts,
            finish_reason=finish_reason,
            max_output_tokens=max_output_tokens,
            schema=json_schema is not None,
            **usage,
            **_elapsed(started, self._clock),
        )
        text = _text(response)

        if finish_reason == "MAX_TOKENS":
            logger.warning("ai_output_truncated", extra={**log_extra, "response_chars": len(text or "")})
            raise AIProviderError(
                "The AI response was too long and was cut off. Try a shorter document or a smaller rewrite scope.",
                retryable=False,
            )
        block_reason = _block_reason(response)
        if not text or not text.strip():
            logger.warning("ai_output_empty", extra={**log_extra, "block_reason": block_reason})
            if block_reason or finish_reason not in (None, "STOP"):
                raise AIProviderError("The AI provider declined to process this document.")
            raise AIProviderError("The AI provider returned an empty response.")

        logger.info("ai_generation", extra={**log_extra, "response_chars": len(text)})
        return text.strip()

    # ------------------------------------------------------------------ embeddings

    # Gemini accepts at most 100 inputs per embedding request.
    _EMBED_BATCH = 100

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        log_extra: dict[str, Any] = {"provider": self.name, "model": self.embedding_model, "task": "embed"}
        started = self._clock()
        attempts_total = 0
        for start in range(0, len(texts), self._EMBED_BATCH):
            batch = texts[start : start + self._EMBED_BATCH]

            def call(timeout_ms: int, batch: list[str] = batch) -> types.EmbedContentResponse:
                config = types.EmbedContentConfig(
                    task_type="SEMANTIC_SIMILARITY",
                    output_dimensionality=self.embedding_dimensions,
                    http_options=types.HttpOptions(timeout=timeout_ms),
                )
                # The SDK's parameter type is an invariant list union; a list[str] is valid at runtime.
                contents: Any = batch
                return self._client.models.embed_content(model=self.embedding_model, contents=contents, config=config)

            try:
                response, attempts = self._call_with_retries("embed", call, log_extra)
            except genai_errors.APIError as exc:
                status = getattr(exc, "code", None)
                logger.warning("ai_embedding_error", extra={**log_extra, "status": status, **_error_details(exc)})
                raise AIProviderError(
                    f"The embedding service returned an error (status {status}).",
                    retryable=status in _RETRYABLE_STATUS,
                ) from exc
            except _TIMEOUT_ERRORS as exc:
                logger.warning("ai_embedding_timeout", extra=log_extra)
                raise AIProviderError("The embedding service timed out.", retryable=True) from exc
            except Exception as exc:
                logger.warning("ai_embedding_failure", extra={**log_extra, "error_type": type(exc).__name__})
                raise AIProviderError("The embedding request failed.", retryable=True) from exc
            attempts_total += attempts
            embeddings = response.embeddings or []
            if len(embeddings) != len(batch) or any(not e.values for e in embeddings):
                raise AIProviderError("The embedding service returned an incomplete response.")
            vectors.extend([list(e.values or []) for e in embeddings])
        logger.info(
            "ai_embedding",
            extra={**log_extra, "texts": len(texts), "attempts": attempts_total, **_elapsed(started, self._clock)},
        )
        return vectors


# ---------------------------------------------------------------------- response helpers (no content logged)


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,120}$")
_MAX_DETAILS = 5


def _error_details(exc: genai_errors.APIError) -> dict[str, Any]:
    """Machine-readable parts of a Google API error: the status enum, ``ErrorInfo.reason`` values
    and ``BadRequest`` field paths. Free-text messages are omitted because they can echo request content."""

    body = exc.details.get("error", exc.details) if isinstance(exc.details, dict) else {}
    details = body.get("details") if isinstance(body, dict) else None
    reasons: list[str] = []
    fields: list[str] = []
    for detail in details if isinstance(details, list) else []:
        if not isinstance(detail, dict):
            continue
        reason = detail.get("reason")
        if isinstance(reason, str) and _IDENTIFIER.match(reason):
            reasons.append(reason)
        for violation in detail.get("fieldViolations") or []:
            field = violation.get("field") if isinstance(violation, dict) else None
            if isinstance(field, str) and _IDENTIFIER.match(field):
                fields.append(field)
    status = exc.status if isinstance(exc.status, str) and _IDENTIFIER.match(exc.status) else None
    return {
        "provider_status": status,
        "provider_reasons": reasons[:_MAX_DETAILS],
        "provider_fields": fields[:_MAX_DETAILS],
    }


def _elapsed(started: float, clock: Callable[[], float]) -> dict[str, int]:
    return {"ai_latency_ms": round((clock() - started) * 1000)}


def _text(response: Any) -> str | None:
    try:
        text = response.text
    except Exception:  # the SDK raises for some non-text candidates
        return None
    return text if isinstance(text, str) else None


def _finish_reason(response: Any) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    if reason is None:
        return None
    return str(getattr(reason, "name", reason))


def _block_reason(response: Any) -> str | None:
    feedback = getattr(response, "prompt_feedback", None)
    reason = getattr(feedback, "block_reason", None) if feedback is not None else None
    return None if reason is None else str(getattr(reason, "name", reason))


def _usage(response: Any) -> dict[str, int | None]:
    """Token counts only (R4)."""

    meta = getattr(response, "usage_metadata", None)

    def count(field: str) -> int | None:
        value = getattr(meta, field, None) if meta is not None else None
        return value if isinstance(value, int) else None

    return {
        "prompt_tokens": count("prompt_token_count"),
        "output_tokens": count("candidates_token_count"),
        "thinking_tokens": count("thoughts_token_count"),
        "cached_tokens": count("cached_content_token_count"),
        "total_tokens": count("total_token_count"),
    }
