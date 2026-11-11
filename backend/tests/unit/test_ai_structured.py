"""Structured AI output (R1, R2): the schema sent to the provider, parse-failure logging, and call-site wiring."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError

from app.ai.structured import parse_model_output, response_schema
from app.core.errors import AIUpstreamError
from app.schemas.job import AIJobExtraction
from app.schemas.resume import AIResumeExtraction
from app.schemas.rewrite import AIRewriteOutput
from app.services.extraction import MAX_OUTPUT_TOKENS_RESUME_EXTRACTION
from app.services.job_extraction import MAX_OUTPUT_TOKENS_JOB_EXTRACTION
from app.services.rewriting.generator import MAX_OUTPUT_TOKENS_REWRITE
from tests.conftest import FakeLLM
from tests.fixtures.documents import SAMPLE_EXTRACTION, SAMPLE_JD, SAMPLE_RESUME_MD

AI_MODELS = [AIResumeExtraction, AIJobExtraction, AIRewriteOutput]
_DROPPED = {"default", "title", "description", "maxLength", "minLength", "maxItems", "minItems"}


def _keywords(node: Any) -> set[str]:
    """Schema keywords used anywhere, skipping field and definition names."""

    found: set[str] = set()
    if isinstance(node, list):
        for item in node:
            found |= _keywords(item)
    elif isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            if key in ("properties", "$defs"):
                for schema in value.values():
                    found |= _keywords(schema)
            else:
                found |= _keywords(value)
    return found


def _refs(node: Any) -> set[str]:
    if isinstance(node, list):
        return set().union(*(_refs(item) for item in node)) if node else set()
    if isinstance(node, dict):
        own = {node["$ref"]} if isinstance(node.get("$ref"), str) else set()
        return own.union(*(_refs(value) for value in node.values()))
    return set()


class TestResponseSchema:
    @pytest.mark.parametrize("model", AI_MODELS)
    def test_only_supported_keywords(self, model: type[BaseModel]) -> None:
        keywords = _keywords(response_schema(model))
        assert not keywords & _DROPPED
        assert keywords <= {"$defs", "$ref", "anyOf", "enum", "items", "properties", "required", "type"}

    @pytest.mark.parametrize("model", AI_MODELS)
    def test_refs_resolve(self, model: type[BaseModel]) -> None:
        schema = response_schema(model)
        for ref in _refs(schema):
            assert ref.startswith("#/$defs/")
            assert ref.removeprefix("#/$defs/") in schema["$defs"]

    def test_field_names_that_look_like_keywords_are_kept(self) -> None:
        resume = response_schema(AIResumeExtraction)
        assert "title" in resume["$defs"]["AIExperience"]["properties"]
        assert "description" in resume["$defs"]["AIProject"]["properties"]
        job = response_schema(AIJobExtraction)
        assert "title" in job["properties"]

    def test_shape_only_limits_left_to_pydantic(self) -> None:
        # Gemini rejected nested maxItems live (400 INVALID_ARGUMENT); limits are enforced after parsing.
        resume = response_schema(AIResumeExtraction)
        assert resume["properties"]["experience"] == {"type": "array", "items": {"$ref": "#/$defs/AIExperience"}}
        assert resume["$defs"]["AIBullet"]["properties"]["type"]["enum"] == ["responsibility", "achievement"]
        with pytest.raises(ValidationError):
            AIResumeExtraction.model_validate({"experience": [{}] * 41})

    @pytest.mark.parametrize("model", [AIResumeExtraction, AIJobExtraction])
    def test_extraction_schemas_require_every_key(self, model: type[BaseModel]) -> None:
        # The prompts ask for every key (null or [] when absent); an all-optional schema let the
        # model omit whole sections live.
        schema = response_schema(model)
        objects = [schema, *schema["$defs"].values()]
        for node in objects:
            assert node["required"] == list(node["properties"])

    def test_nullable_fields_still_accept_null(self) -> None:
        resume = response_schema(AIResumeExtraction)
        assert resume["properties"]["name"] == {"anyOf": [{"$ref": "#/$defs/AIValue"}, {"type": "null"}]}
        assert resume["$defs"]["AIValue"]["properties"]["value"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}

    def test_rewrite_sections_are_optional_but_their_contents_are_not(self) -> None:
        # The rewrite prompt asks for only the requested sections.
        rewrite = response_schema(AIRewriteOutput, optional_sections=True)
        assert "required" not in rewrite
        bullet = rewrite["$defs"]["AIRewriteBullet"]
        assert bullet["required"] == list(bullet["properties"])
        assert response_schema(AIRewriteOutput)["required"] == list(rewrite["properties"])

    def test_returns_a_copy(self) -> None:
        response_schema(AIRewriteOutput)["properties"].clear()
        assert response_schema(AIRewriteOutput)["properties"]

    def test_sample_extraction_still_validates(self) -> None:
        # The schema is advisory; Pydantic remains the check and must accept well-formed output.
        AIResumeExtraction.model_validate(SAMPLE_EXTRACTION)


class _Out(BaseModel):
    name: str = Field(max_length=10)
    items: list[int] = Field(default_factory=list)


def _parse(raw: str) -> _Out:
    return parse_model_output(
        raw, _Out, provider="fake", task="unit", prompt_version="v1", user_message="Unexpected format."
    )


def _warning(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    (record,) = [vars(r) for r in caplog.records if r.getMessage() == "ai_invalid_output"]
    return record


class TestParseModelOutput:
    def test_valid(self) -> None:
        assert _parse('{"name": "ok", "items": [1]}') == _Out(name="ok", items=[1])

    def test_invalid_json_logs_reason_without_content(self, caplog: pytest.LogCaptureFixture) -> None:
        with pytest.raises(AIUpstreamError, match="Unexpected format"):
            _parse('{"name": "Jane Secret", "items": [1, ')
        record = _warning(caplog)
        assert record["reason"] == "invalid_json"
        assert record["task"] == "unit"
        assert isinstance(record["json_error_pos"], int)
        assert "Jane Secret" not in repr(record)

    def test_non_object(self, caplog: pytest.LogCaptureFixture) -> None:
        with pytest.raises(AIUpstreamError):
            _parse('["Jane Secret"]')
        record = _warning(caplog)
        assert record["reason"] == "not_an_object"
        assert record["json_type"] == "list"

    def test_schema_mismatch_logs_paths_not_values(self, caplog: pytest.LogCaptureFixture) -> None:
        with pytest.raises(AIUpstreamError):
            _parse(json.dumps({"name": "Jane Secret Longname", "items": ["x"]}))
        record = _warning(caplog)
        assert record["reason"] == "schema_mismatch"
        assert record["error_count"] == 2
        assert record["errors"] == ["name: string_too_long", "items.0: int_parsing"]
        assert "Jane Secret" not in repr(record)


def test_every_ai_call_sends_its_schema_cap_and_task(client: TestClient, fake_llm: FakeLLM) -> None:
    res = client.post("/api/v1/resumes", files={"file": ("cv.md", SAMPLE_RESUME_MD.encode(), "text/markdown")})
    assert res.status_code == 201, res.text
    resume_id = res.json()["id"]
    res = client.post("/api/v1/jobs", data={"text": SAMPLE_JD})
    assert res.status_code == 201, res.text
    res = client.post("/api/v1/rewrites", json={"resume_id": resume_id, "job_id": res.json()["id"]})
    assert res.status_code == 201, res.text

    calls = {call["task"]: call for call in fake_llm.generate_calls}
    assert set(calls) == {"resume_extraction", "job_extraction", "rewrite_full"}
    assert calls["resume_extraction"]["json_schema"] == response_schema(AIResumeExtraction)
    assert calls["resume_extraction"]["max_output_tokens"] == MAX_OUTPUT_TOKENS_RESUME_EXTRACTION
    assert calls["job_extraction"]["json_schema"] == response_schema(AIJobExtraction)
    assert calls["job_extraction"]["max_output_tokens"] == MAX_OUTPUT_TOKENS_JOB_EXTRACTION
    assert calls["rewrite_full"]["json_schema"] == response_schema(AIRewriteOutput, optional_sections=True)
    assert calls["rewrite_full"]["max_output_tokens"] == MAX_OUTPUT_TOKENS_REWRITE
