"""Application error types and the single JSON error envelope.

Every error response has the shape::

    {"detail": "<human message>", "error": {"code": "...", "message": "...", "request_id": "..."}}

``detail`` is kept at the top level for compatibility with the existing
frontend, which reads ``body.detail``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.headers = headers


class InvalidFileError(AppError):
    code = "invalid_file"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class AIUnavailableError(AppError):
    status_code = 503
    code = "ai_not_configured"


class AIUpstreamError(AppError):
    status_code = 502
    code = "ai_upstream_error"


class AuthenticationError(AppError):
    status_code = 401
    code = "not_authenticated"


class CsrfError(AppError):
    status_code = 403
    code = "csrf_failed"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message, headers={"Retry-After": str(max(1, retry_after_seconds))})
        self.retry_after_seconds = retry_after_seconds


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    fields: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message, "request_id": request_id_var.get()}
    if fields:
        error["fields"] = fields
    return JSONResponse(status_code=status_code, content={"detail": message, "error": error}, headers=headers)


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(exc.status_code, exc.code, exc.message, headers=exc.headers)


async def _http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    code = _STATUS_CODES.get(exc.status_code, "error")
    return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Deliberately omit the offending `input` values: they may contain
    # passwords or document text.
    fields = [{"loc": [str(part) for part in err.get("loc", ())], "msg": err.get("msg", "")} for err in exc.errors()]
    return error_response(422, "validation_error", "Request validation failed.", fields=fields)


async def _unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", extra={"error_type": type(exc).__name__})
    return error_response(500, "internal_error", "An unexpected error occurred.")


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
