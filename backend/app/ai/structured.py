"""Structured AI output: the JSON Schema sent to the provider and the parsing of its reply.

The schema constrains the model's output (R1); Pydantic validation of the reply remains the
real check, because nothing the model returns is trusted. Parse failures are logged with a
machine-readable reason and field paths only, never the model's text (R2).
"""

from __future__ import annotations

import json
import logging
from functools import cache
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.errors import AIUpstreamError

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

# Keywords not sent to the provider: developer-facing ones, and every length/count limit. Gemini
# rejected the full Pydantic schema live (HTTP 400 INVALID_ARGUMENT, with nested ``maxItems`` the
# likely trigger: its documented "too many states" limit), so the provider schema describes shape
# only. Pydantic still enforces every limit after parsing.
_DROPPED_KEYWORDS = frozenset({"default", "title", "description", "maxLength", "minLength", "maxItems", "minItems"})
# Maps whose keys are field or definition names, not schema keywords.
_NAME_MAPS = frozenset({"properties", "$defs"})
_MAX_LOGGED_ERRORS = 5


def _sanitise(node: Any) -> Any:
    """Drop unsent keywords and mark every property required (nullable ones still accept null).

    The prompts ask for every key, using null or [] when the document does not state a value. A
    schema that left fields optional let the model omit whole sections (seen live: an extraction
    with no experience, education or skills), so the schema states the same contract as the prompt.
    """

    if isinstance(node, list):
        return [_sanitise(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROPPED_KEYWORDS:
            continue
        if key in _NAME_MAPS and isinstance(value, dict):
            cleaned[key] = {name: _sanitise(schema) for name, schema in value.items()}
        else:
            cleaned[key] = _sanitise(value)
    if isinstance(cleaned.get("properties"), dict):
        cleaned["required"] = list(cleaned["properties"])
    return cleaned


@cache
def _schema_json(model: type[BaseModel], optional_sections: bool) -> str:
    schema = _sanitise(model.model_json_schema(mode="validation"))
    if optional_sections:
        schema.pop("required", None)
    return json.dumps(schema)


def response_schema(model: type[BaseModel], *, optional_sections: bool = False) -> dict[str, Any]:
    """The provider-facing JSON Schema for ``model`` (a fresh copy each call).

    ``optional_sections`` leaves the top-level keys optional, for prompts that ask for only some
    sections (the rewrite); everything nested stays required.
    """

    schema: dict[str, Any] = json.loads(_schema_json(model, optional_sections))
    return schema


def parse_model_output(
    raw_text: str,
    model: type[ModelT],
    *,
    provider: str,
    task: str,
    prompt_version: str,
    user_message: str,
) -> ModelT:
    """Parse and validate the provider's JSON text, or log why not and raise :class:`AIUpstreamError`."""

    log_extra: dict[str, Any] = {
        "provider": provider,
        "task": task,
        "prompt_version": prompt_version,
        "response_chars": len(raw_text),
    }
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        # The decoder's message names the syntax problem ("Expecting ',' delimiter"), not content.
        log_extra.update(reason="invalid_json", json_error=exc.msg, json_error_pos=exc.pos)
        logger.warning("ai_invalid_output", extra=log_extra)
        raise AIUpstreamError(user_message) from exc
    if not isinstance(data, dict):
        log_extra.update(reason="not_an_object", json_type=type(data).__name__)
        logger.warning("ai_invalid_output", extra=log_extra)
        raise AIUpstreamError(user_message)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False, include_context=False)
        log_extra.update(
            reason="schema_mismatch",
            error_count=len(errors),
            # Field paths and error types only (e.g. "experience.3.bullets: too_long").
            errors=[
                f"{'.'.join(str(part) for part in error['loc'])}: {error['type']}"
                for error in errors[:_MAX_LOGGED_ERRORS]
            ],
        )
        logger.warning("ai_invalid_output", extra=log_extra)
        raise AIUpstreamError(user_message) from exc
