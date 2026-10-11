"""The FastAPI application: routes, error handling, OpenAPI document."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from analysis import __version__
from analysis.api.contracts import (
    ChangedSymbolsRequest,
    ChangedSymbolsResponse,
    Health,
    Problem,
    ProblemError,
)
from analysis.api.logs import configure_logging
from analysis.api.middleware import BodyLimitMiddleware, RequestContextMiddleware, request_id_of
from analysis.api.problems import PROBLEM_MEDIA_TYPE, ApiError, problem_response
from analysis.api.settings import Settings
from analysis.api.snapshots import SnapshotNotFound, SnapshotStore
from analysis.diff import DiffParseError, parse_unified_diff
from analysis.symbols import Limits, detect_changed_symbols

logger = logging.getLogger("analysis.api")
router = APIRouter()


def _problem(description: str) -> dict[str, Any]:
    # The description is spelled out because FastAPI's default is the standard
    # phrase for the status code, and Python renamed two of those in 3.13
    # ("Unprocessable Entity" became "Unprocessable Content"). Left to the
    # default, the contract file would depend on the Python version.
    return {"model": Problem, "description": description}


@router.get("/healthz", tags=["operations"], summary="Is the process alive?")
def healthz() -> Health:
    return Health(status="ok", version=__version__)


@router.get(
    "/readyz",
    tags=["operations"],
    summary="Can the service do its job right now?",
    responses={503: _problem("The snapshot directory is not available.")},
)
def readyz(request: Request) -> Health:
    store: SnapshotStore = request.app.state.snapshots
    if not store.is_ready():
        raise ApiError(503, "not_ready", "Not ready", "The snapshot directory is not available.")
    return Health(status="ok", version=__version__)


@router.post(
    "/v1/changed-symbols",
    tags=["analysis"],
    summary="Which functions, methods and classes does this change touch?",
    responses={
        411: _problem("The request body has no declared length, or is chunked."),
        413: _problem("The request body is larger than the service accepts."),
        422: _problem("The request is malformed, or names a snapshot that does not exist."),
        500: _problem("The service failed. The body carries a request id to quote."),
    },
)
def changed_symbols(body: ChangedSymbolsRequest, request: Request) -> ChangedSymbolsResponse:
    # A plain `def`, not `async def`: FastAPI then runs it on a worker thread.
    # Parsing is CPU work, and doing it on the event loop would freeze every
    # other request, health checks included, until it finished.
    settings: Settings = request.app.state.settings
    store: SnapshotStore = request.app.state.snapshots

    try:
        base = store.open(body.base.snapshot)
        head = store.open(body.head.snapshot)
    except SnapshotNotFound as error:
        raise ApiError(
            422,
            "snapshot_not_found",
            "Snapshot not found",
            f"No snapshot named {error.snapshot_id!r} exists.",
        ) from error
    try:
        diffs = parse_unified_diff(body.diff)
    except DiffParseError as error:
        raise ApiError(422, "invalid_diff", "Invalid diff", str(error)) from error

    change_set = detect_changed_symbols(
        diffs,
        base,
        head,
        limits=Limits(
            max_file_bytes=settings.max_file_bytes,
            max_files=settings.max_files,
            time_budget_seconds=settings.time_budget_seconds,
        ),
    )
    logger.info(
        "changed symbols",
        extra={
            "fields": {
                "request_id": request_id_of(request.scope),
                "base_commit": body.base.commit,
                "head_commit": body.head.commit,
                "files": len(change_set.files),
                "symbols": sum(len(change.symbols) for change in change_set.files),
                "complete": change_set.complete,
            }
        },
    )
    return ChangedSymbolsResponse.from_domain(change_set)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own settings; the server reads the environment."""
    settings = settings if settings is not None else Settings.from_env()
    configure_logging()

    app = FastAPI(
        title="BestTest analysis service",
        version=__version__,
        description=(
            "Stateless analysis stages for the BestTest backend. Internal: it has no "
            "authentication and must not be reachable from outside the deployment."
        ),
    )
    app.state.settings = settings
    app.state.snapshots = SnapshotStore(settings.snapshot_root)

    # Middleware added last runs first, so the request context wraps everything.
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(RequestContextMiddleware)

    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)

    app.include_router(router)
    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    return app


async def _handle_api_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ApiError)
    return problem_response(
        error.status,
        error.code,
        error.title,
        error.detail,
        request_id=request_id_of(request.scope),
    )


async def _handle_validation_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    # Only the location and the message are returned. Pydantic's full error also
    # carries the rejected input, which here could be an entire diff.
    errors = [
        ProblemError(
            location=".".join(str(part) for part in item.get("loc", ())),
            message=str(item.get("msg", "invalid value")),
        )
        for item in error.errors()
    ]
    return problem_response(
        422,
        "invalid_request",
        "Invalid request",
        "The request body does not match the contract.",
        request_id=request_id_of(request.scope),
        errors=errors,
    )


async def _handle_http_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, StarletteHTTPException)
    codes = {404: "not_found", 405: "method_not_allowed"}
    return problem_response(
        error.status_code,
        codes.get(error.status_code, "http_error"),
        str(error.detail),
        request_id=request_id_of(request.scope),
        headers=error.headers,
    )


def _openapi(app: FastAPI) -> dict[str, Any]:
    """FastAPI's OpenAPI document, corrected to state the real error media type."""
    if app.openapi_schema is None:
        schema = FastAPI.openapi(app)
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                for response in operation.get("responses", {}).values():
                    content = response.get("content", {})
                    json_body = content.get("application/json", {})
                    if json_body.get("schema", {}).get("$ref", "").endswith("/Problem"):
                        content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
        app.openapi_schema = schema
    return app.openapi_schema
