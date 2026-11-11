"""Structured logging with request correlation and content redaction.

Resume and job-description text, prompts, passwords and tokens must never be
logged. Code should not pass them to the logger in the first place; as a second
line of defence the formatters redact any ``extra`` field whose name is on the
sensitive list.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from app.core.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

SENSITIVE_KEYS = frozenset(
    {
        "resume_text",
        "jd_text",
        "text",
        "content",
        "prompt",
        "system",
        "password",
        "token",
        "session",
        "cookie",
        "authorization",
        "api_key",
        "gemini_api_key",
    }
)
REDACTED = "[REDACTED]"

# Attributes present on every LogRecord; anything else came from `extra=`.
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "request_id",
    "taskName",
    # uvicorn attaches an ANSI-coloured duplicate of the message for its own console formatter.
    "color_message",
}


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: (REDACTED if key.lower() in SENSITIVE_KEYS else value)
        for key, value in vars(record).items()
        if key not in _STANDARD_ATTRS
    }


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        payload.update(_extras(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = _extras(record)
        if extras:
            line += " " + " ".join(f"{key}={value}" for key, value in extras.items())
        return line


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonFormatter() if settings.effective_log_format == "json" else TextFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Our middleware writes one access line per request; avoid duplicates.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    # The Google SDK and httpx log request details at INFO; keep them quiet.
    for noisy in ("httpx", "httpx2", "httpcore", "google_genai", "google.genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
