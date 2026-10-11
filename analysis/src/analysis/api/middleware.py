"""Cross-cutting request handling: identity, logging, size limits.

Both classes are plain ASGI middleware. ASGI is the interface between a Python
web server and an application: the server calls ``app(scope, receive, send)``
once per request, where ``scope`` describes the request and ``send`` emits the
response. A middleware is an app that wraps another app.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from analysis.api.problems import problem_response

logger = logging.getLogger("analysis.api")

REQUEST_ID_HEADER = "x-request-id"
_ACCEPTABLE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_METHODS_WITH_BODY = frozenset({"POST", "PUT", "PATCH"})
_PROBE_PATHS = frozenset({"/healthz", "/readyz"})


def request_id_of(scope: Scope) -> str | None:
    state = scope.get("state")
    return state.get("request_id") if isinstance(state, dict) else None


class RequestContextMiddleware:
    """Give every request an id, log one line about it, and catch crashes.

    The caller may supply the id in ``X-Request-ID`` so that one id follows a
    piece of work across services. It is echoed back only if it is short and
    made of harmless characters; anything else is replaced, because the value
    ends up in log lines and response headers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = _header(scope, REQUEST_ID_HEADER)
        request_id = (
            supplied
            if supplied and _ACCEPTABLE_REQUEST_ID.fullmatch(supplied)
            else uuid.uuid4().hex
        )
        scope.setdefault("state", {})["request_id"] = request_id

        status = 0
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # Nothing below handled it, so this is a bug. Log the traceback for
            # us; tell the caller only that it happened and how to refer to it.
            logger.exception("unhandled error", extra={"fields": {"request_id": request_id}})
            if status == 0:
                response = problem_response(
                    500,
                    "internal_error",
                    "Internal error",
                    "The service failed to process the request.",
                    request_id=request_id,
                )
                await response(scope, receive, send_with_id)
        finally:
            # A healthy probe arrives every few seconds and says nothing new.
            # Keep it out of the normal log; a failing one still shows up.
            routine = scope["path"] in _PROBE_PATHS and status == 200
            logger.log(
                logging.DEBUG if routine else logging.INFO,
                "request",
                extra={
                    "fields": {
                        "request_id": request_id,
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )


class BodyLimitMiddleware:
    """Refuse request bodies that are too large, before reading them.

    A body must announce its size in ``Content-Length``. The web server makes
    sure no more than that arrives, so checking the header is enough, and an
    oversized request costs the service nothing.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _METHODS_WITH_BODY:
            await self.app(scope, receive, send)
            return

        declared = _header(scope, "content-length")
        # A chunked body has no fixed size, and HTTP lets Transfer-Encoding
        # override Content-Length when both are sent. Accepting it would let a
        # caller declare five bytes and then stream five gigabytes.
        chunked = _header(scope, "transfer-encoding") is not None
        if chunked or declared is None or not declared.isdecimal():
            response = problem_response(
                411,
                "length_required",
                "Length required",
                "Send the request body with a Content-Length header.",
                request_id=request_id_of(scope),
            )
        elif int(declared) > self.max_bytes:
            response = problem_response(
                413,
                "request_too_large",
                "Request too large",
                f"The request body is {declared} bytes; the limit is {self.max_bytes}.",
                request_id=request_id_of(scope),
            )
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)


def _header(scope: Scope, name: str) -> str | None:
    wanted = name.encode()
    for key, value in scope.get("headers", []):
        if key == wanted:
            decoded: str = value.decode("latin-1")
            return decoded
    return None
