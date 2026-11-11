"""Gemini adapter: request configuration, retries within one deadline, truncation and usage logging,
and error mapping. The SDK client is replaced; no network calls are made."""

from __future__ import annotations

import logging
from typing import Any, ClassVar, cast

import httpx
import httpx2
import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.ai import gemini as gemini_module
from app.ai.base import AIProvider, AIProviderError
from app.ai.factory import build_ai_provider
from app.core.config import Settings


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result: Any = None
        self.error: Exception | None = None
        # Optional per-attempt outcomes (exceptions or responses), consumed in order.
        self.outcomes: list[Any] = []
        self.clock: _Clock | None = None
        self.attempt_seconds = 0.0  # simulated duration of each attempt
        self.embed_calls: list[dict[str, Any]] = []

    def _next(self) -> Any:
        if self.clock is not None:
            self.clock.now += self.attempt_seconds
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        if self.error is not None:
            raise self.error
        return self.result

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._next()

    def embed_content(self, **kwargs: Any) -> Any:
        self.embed_calls.append(kwargs)
        return self._next()


class _FakeClient:
    instances: ClassVar[list[_FakeClient]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.models = _FakeModels()
        _FakeClient.instances.append(self)


class _Response:
    def __init__(self, text: str | None) -> None:
        self.text = text


def _sdk_response(
    text: str | None,
    *,
    finish: types.FinishReason = types.FinishReason.STOP,
    prompt_tokens: int = 1200,
    output_tokens: int = 300,
    thinking_tokens: int | None = 50,
) -> types.GenerateContentResponse:
    parts = [types.Part(text=text)] if text is not None else []
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts), finish_reason=finish)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt_tokens,
            candidates_token_count=output_tokens,
            thoughts_token_count=thinking_tokens,
            total_token_count=prompt_tokens + output_tokens + (thinking_tokens or 0),
        ),
    )


def _server_error(status: int = 503) -> genai_errors.APIError:
    return genai_errors.ServerError(status, {"error": {"message": "overloaded"}})


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


def _make(monkeypatch: pytest.MonkeyPatch, clock: _Clock, **kwargs: Any) -> gemini_module.GeminiProvider:
    _FakeClient.instances.clear()
    monkeypatch.setattr("app.ai.gemini.genai.Client", _FakeClient)
    options: dict[str, Any] = {
        "api_key": "test-key",
        "model": "gemini-test",
        "timeout_seconds": 12.5,
        "max_retries": 2,
        "total_timeout_seconds": 90,
    }
    options.update(kwargs)
    provider = gemini_module.GeminiProvider(**options)
    provider._clock = clock
    provider._sleep = clock.sleep
    _models(provider).clock = clock
    return provider


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> gemini_module.GeminiProvider:
    return _make(monkeypatch, clock)


def _models(provider: gemini_module.GeminiProvider) -> _FakeModels:
    return cast(_FakeModels, provider._client.models)


def _records(caplog: pytest.LogCaptureFixture, message: str) -> list[dict[str, Any]]:
    """The fields of each log record with this message (``extra`` values included)."""

    return [vars(r) for r in caplog.records if r.getMessage() == message]


# ---------------------------------------------------------------------- configuration


def test_implements_provider_protocol(provider: gemini_module.GeminiProvider) -> None:
    assert isinstance(provider, AIProvider)


def test_client_has_timeout_and_no_sdk_retries(provider: gemini_module.GeminiProvider) -> None:
    kwargs = _FakeClient.instances[-1].kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["http_options"].timeout == 12500
    # The adapter owns retries so that one deadline covers them all.
    assert kwargs["http_options"].retry_options.attempts == 1


def test_request_uses_system_channel_json_mode_schema_and_cap(provider: gemini_module.GeminiProvider) -> None:
    _models(provider).result = _Response('{"ok": true}')
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    assert (
        provider.generate_json(system="SYS", prompt="USER", json_schema=schema, max_output_tokens=4096, task="t")
        == '{"ok": true}'
    )
    call = _models(provider).calls[-1]
    assert call["model"] == "gemini-test"
    assert call["contents"] == "USER"
    config = call["config"]
    assert config.system_instruction == "SYS"
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == schema
    assert config.max_output_tokens == 4096
    assert config.http_options.timeout == 12500


# ---------------------------------------------------------------------- retries and the overall deadline (R3)


def test_retryable_error_is_retried_then_succeeds(
    provider: gemini_module.GeminiProvider, clock: _Clock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.ai.gemini")
    _models(provider).outcomes = [_server_error(503), _sdk_response('{"a": 1}')]
    assert provider.generate_json(system="s", prompt="p") == '{"a": 1}'
    assert len(_models(provider).calls) == 2
    assert len(clock.sleeps) == 1
    assert 1.0 <= clock.sleeps[0] <= 1.5
    (retry,) = _records(caplog, "ai_provider_retry")
    assert retry["status"] == 503
    (done,) = _records(caplog, "ai_generation")
    assert done["attempts"] == 2


def test_retries_stop_at_max_retries(provider: gemini_module.GeminiProvider) -> None:
    _models(provider).error = _server_error(503)
    with pytest.raises(AIProviderError, match="status 503"):
        provider.generate_json(system="s", prompt="p")
    assert len(_models(provider).calls) == 3  # 1 + AI_MAX_RETRIES


# google-genai's default transport is httpx2 (its errors are not httpx subclasses); httpx is used only on request.
SDK_TRANSPORT_ERRORS = [
    httpx2.ReadTimeout("t"),
    httpx2.ConnectError("refused"),
    httpx.ReadTimeout("t"),
    httpx.ConnectError("refused"),
]


@pytest.mark.parametrize("error", SDK_TRANSPORT_ERRORS, ids=lambda e: f"{type(e).__module__}.{type(e).__name__}")
def test_transport_errors_from_either_http_library_are_retried(
    provider: gemini_module.GeminiProvider, error: Exception
) -> None:
    _models(provider).outcomes = [error, _sdk_response('{"a": 1}')]
    assert provider.generate_json(system="s", prompt="p") == '{"a": 1}'
    assert len(_models(provider).calls) == 2


@pytest.mark.parametrize("error", [httpx2.ReadTimeout("t"), httpx.ReadTimeout("t")], ids=["httpx2", "httpx"])
def test_timeouts_from_either_http_library_are_reported_as_timeouts(
    monkeypatch: pytest.MonkeyPatch, clock: _Clock, error: Exception
) -> None:
    provider = _make(monkeypatch, clock, max_retries=0)
    _models(provider).error = error
    with pytest.raises(AIProviderError, match="timed out") as exc_info:
        provider.generate_json(system="s", prompt="p")
    assert exc_info.value.retryable


def test_zero_retries_means_one_attempt(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> None:
    provider = _make(monkeypatch, clock, max_retries=0)
    _models(provider).error = httpx.ReadTimeout("timed out")
    with pytest.raises(AIProviderError, match="timed out"):
        provider.generate_json(system="s", prompt="p")
    assert len(_models(provider).calls) == 1
    assert clock.sleeps == []


def test_non_retryable_error_is_not_retried(provider: gemini_module.GeminiProvider) -> None:
    _models(provider).error = genai_errors.ClientError(400, {"error": {"message": "bad schema"}})
    with pytest.raises(AIProviderError, match="status 400") as exc_info:
        provider.generate_json(system="s", prompt="p")
    assert not exc_info.value.retryable
    assert len(_models(provider).calls) == 1


def test_attempt_timeout_shrinks_to_the_time_left(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> None:
    provider = _make(monkeypatch, clock, timeout_seconds=60, total_timeout_seconds=90, max_retries=2)
    models = _models(provider)
    models.attempt_seconds = 60  # each attempt uses its whole timeout
    models.outcomes = [httpx.ReadTimeout("t"), _sdk_response("{}")]
    provider.generate_json(system="s", prompt="p")
    first, second = (call["config"].http_options.timeout for call in models.calls)
    assert first == 60_000
    # 90 s budget - 60 s first attempt - ~1 s back-off leaves about 29 s.
    assert 28_000 <= second <= 29_000


def test_no_retry_once_the_deadline_is_nearly_spent(
    monkeypatch: pytest.MonkeyPatch, clock: _Clock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.ai.gemini")
    provider = _make(monkeypatch, clock, timeout_seconds=60, total_timeout_seconds=61, max_retries=5)
    models = _models(provider)
    models.attempt_seconds = 60
    models.error = httpx.ReadTimeout("t")
    with pytest.raises(AIProviderError, match="timed out"):
        provider.generate_json(system="s", prompt="p")
    assert len(models.calls) == 1
    assert clock.sleeps == []
    assert _records(caplog, "ai_deadline_exhausted")
    (timeout,) = _records(caplog, "ai_provider_timeout")
    assert timeout["ai_latency_ms"] == 60_000


def test_worst_case_duration_is_bounded_by_the_deadline(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> None:
    provider = _make(monkeypatch, clock, timeout_seconds=60, total_timeout_seconds=90, max_retries=5)
    models = _models(provider)
    started = clock.now

    def slow_failure(**kwargs: Any) -> Any:
        models.calls.append(kwargs)
        clock.now += kwargs["config"].http_options.timeout / 1000
        raise httpx.ReadTimeout("t")

    monkeypatch.setattr(models, "generate_content", slow_failure)
    with pytest.raises(AIProviderError):
        provider.generate_json(system="s", prompt="p")
    assert clock.now - started <= 90 + 0.01


# ---------------------------------------------------------------------- finish reason and usage (R2, R4)


def test_usage_is_logged_without_content(
    provider: gemini_module.GeminiProvider, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.ai.gemini")
    _models(provider).result = _sdk_response('{"name": "Jane Secret"}')
    provider.generate_json(
        system="SYSTEM SECRET", prompt="RESUME SECRET", json_schema={"type": "object"}, task="resume_extraction"
    )
    (record,) = _records(caplog, "ai_generation")
    assert record["task"] == "resume_extraction"
    assert record["finish_reason"] == "STOP"
    assert (record["prompt_tokens"], record["output_tokens"], record["thinking_tokens"], record["total_tokens"]) == (
        1200,
        300,
        50,
        1550,
    )
    assert record["schema"] is True
    assert record["attempts"] == 1
    dumped = repr(record)
    for secret in ("Jane Secret", "SYSTEM SECRET", "RESUME SECRET", "test-key"):
        assert secret not in dumped


def test_truncated_output_is_an_error_with_reason_logged(
    provider: gemini_module.GeminiProvider, caplog: pytest.LogCaptureFixture
) -> None:
    _models(provider).result = _sdk_response('{"name": "Jane', finish=types.FinishReason.MAX_TOKENS)
    with pytest.raises(AIProviderError, match="cut off") as exc_info:
        provider.generate_json(system="s", prompt="p", max_output_tokens=100)
    assert not exc_info.value.retryable
    (record,) = _records(caplog, "ai_output_truncated")
    assert record["finish_reason"] == "MAX_TOKENS"
    assert record["max_output_tokens"] == 100
    assert "Jane" not in repr(record)


def test_blocked_output_reports_a_decline(
    provider: gemini_module.GeminiProvider, caplog: pytest.LogCaptureFixture
) -> None:
    _models(provider).result = _sdk_response(None, finish=types.FinishReason.SAFETY)
    with pytest.raises(AIProviderError, match="declined"):
        provider.generate_json(system="s", prompt="p")
    (record,) = _records(caplog, "ai_output_empty")
    assert record["finish_reason"] == "SAFETY"


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_response_raises(provider: gemini_module.GeminiProvider, text: str | None) -> None:
    _models(provider).result = _Response(text)
    with pytest.raises(AIProviderError, match="empty response"):
        provider.generate_json(system="s", prompt="p")


# ---------------------------------------------------------------------- error mapping


def test_rate_limit_maps_to_retryable_error(provider: gemini_module.GeminiProvider) -> None:
    _models(provider).error = genai_errors.ClientError(
        429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    )
    with pytest.raises(AIProviderError, match="rate limiting") as exc_info:
        provider.generate_json(system="s", prompt="p")
    assert exc_info.value.retryable


def test_server_error_maps_to_provider_error(provider: gemini_module.GeminiProvider) -> None:
    _models(provider).error = _server_error(503)
    with pytest.raises(AIProviderError, match="status 503"):
        provider.generate_json(system="s", prompt="p")


def test_timeout_maps_to_provider_error(provider: gemini_module.GeminiProvider) -> None:
    _models(provider).error = httpx.ReadTimeout("timed out")
    with pytest.raises(AIProviderError, match="timed out"):
        provider.generate_json(system="s", prompt="p")


def test_unexpected_error_does_not_leak_details(provider: gemini_module.GeminiProvider) -> None:
    _models(provider).error = RuntimeError("secret internal detail with api_key=abc")
    with pytest.raises(AIProviderError) as exc_info:
        provider.generate_json(system="s", prompt="p")
    assert "secret internal detail" not in str(exc_info.value)
    assert len(_models(provider).calls) == 1  # unknown errors are not retried


def test_provider_error_logs_identifiers_but_not_messages(
    provider: gemini_module.GeminiProvider, caplog: pytest.LogCaptureFixture
) -> None:
    _models(provider).error = genai_errors.ClientError(
        400,
        {
            "error": {
                "code": 400,
                "message": "Bad value near 'Jane Secret'",
                "status": "INVALID_ARGUMENT",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"},
                    {
                        "@type": "type.googleapis.com/google.rpc.BadRequest",
                        "fieldViolations": [
                            {"field": "generation_config.response_json_schema", "description": "Jane Secret"},
                            {"field": "not an identifier: Jane Secret", "description": "x"},
                        ],
                    },
                ],
            }
        },
    )
    with pytest.raises(AIProviderError, match="status 400"):
        provider.generate_json(system="s", prompt="p")
    (record,) = _records(caplog, "ai_provider_error")
    assert record["provider_status"] == "INVALID_ARGUMENT"
    assert record["provider_reasons"] == ["API_KEY_INVALID"]
    assert record["provider_fields"] == ["generation_config.response_json_schema"]
    assert "Jane Secret" not in repr(record)


# ---------------------------------------------------------------------- embeddings


def _embed_response(count: int) -> types.EmbedContentResponse:
    return types.EmbedContentResponse(embeddings=[types.ContentEmbedding(values=[0.1, 0.2]) for _ in range(count)])


def test_embeddings_retry_within_the_deadline(provider: gemini_module.GeminiProvider, clock: _Clock) -> None:
    _models(provider).outcomes = [_server_error(500), _embed_response(2)]
    assert provider.embed(["a", "b"]) == [[0.1, 0.2], [0.1, 0.2]]
    calls = _models(provider).embed_calls
    assert len(calls) == 2
    assert calls[0]["config"].http_options.timeout == 12500
    assert len(clock.sleeps) == 1


def test_embedding_error_maps_to_provider_error(provider: gemini_module.GeminiProvider) -> None:
    _models(provider).error = genai_errors.ClientError(400, {"error": {"message": "bad"}})
    with pytest.raises(AIProviderError, match="status 400"):
        provider.embed(["a"])


# ---------------------------------------------------------------------- factory


def test_factory_returns_none_without_key() -> None:
    settings = Settings(_env_file=None, gemini_api_key=None)
    assert build_ai_provider(settings) is None


def test_factory_builds_gemini_with_configured_model_and_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ai.gemini.genai.Client", _FakeClient)
    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        gemini_model="gemini-custom",
        ai_timeout_seconds=30,
        ai_total_timeout_seconds=45,
        ai_max_retries=1,
    )
    provider = build_ai_provider(settings)
    assert isinstance(provider, gemini_module.GeminiProvider)
    assert provider.model == "gemini-custom"
    assert (provider.timeout_seconds, provider.total_timeout_seconds, provider.max_retries) == (30, 45, 1)
