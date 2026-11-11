"""Pure-ASGI middleware: request correlation/access logging, body size limits and the proxy access key."""

from __future__ import annotations

import hmac
import logging
import re
import time
import uuid

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response
from app.core.logging import request_id_var

access_logger = logging.getLogger("app.access")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware:
    """Assigns a request id, echoes it as ``X-Request-ID`` and logs one access line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        status_code = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
                # API responses are per-user data: unless a route chose a policy, no browser or CDN
                # (e.g. a caching rewrite proxy) may store them.
                if not any(name.lower() == b"cache-control" for name, _ in headers):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            access_logger.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)


class RequestTooLargeError(StarletteHTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request body is too large.")


class BodySizeLimitMiddleware:
    """Rejects request bodies over ``max_bytes`` without buffering them.

    Checks ``Content-Length`` up front and also counts streamed (chunked)
    bodies, so a client cannot bypass the limit by omitting the header.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestTooLargeError()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except RequestTooLargeError:
            if response_started:
                raise
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = error_response(413, "payload_too_large", "Request body is too large.")
        await response(scope, receive, send)


ACCESS_KEY_HEADER = b"x-backend-access-key"
# The only unauthenticated path: the liveness probe used by Render's and Docker's health checks, which
# cannot send the key. It reveals nothing ({"status": "ok"}, no dependency checks).
ACCESS_KEY_EXEMPT_PATHS = frozenset({"/api/v1/health"})


class BackendAccessKeyMiddleware:
    """Refuses requests that did not come through the trusted frontend proxy.

    The proxy (Vercel) adds ``X-Backend-Access-Key`` server-side, so the browser never sees the key.
    Requests sent straight to the API host, which could also forge ``X-Forwarded-For`` to dodge per-IP
    rate limits, are answered with 403 before any route runs. Only installed when the key is configured.
    """

    def __init__(self, app: ASGIApp, access_key: str) -> None:
        self.app = app
        self.access_key = access_key.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in ACCESS_KEY_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        provided = b""
        for name, value in scope["headers"]:
            if name == ACCESS_KEY_HEADER:
                provided = value
                break
        if not hmac.compare_digest(provided, self.access_key):
            response = error_response(403, "forbidden", "Requests must be sent through the application's website.")
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
