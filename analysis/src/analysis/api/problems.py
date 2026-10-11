"""One error format for every failure the service can report."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fastapi.responses import JSONResponse

from analysis.api.contracts import Problem, ProblemError

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ApiError(Exception):
    """An expected failure that maps to a specific HTTP status and code."""

    def __init__(self, status: int, code: str, title: str, detail: str | None = None) -> None:
        super().__init__(detail or title)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


def problem_response(
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    *,
    request_id: str | None = None,
    errors: Sequence[ProblemError] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    problem = Problem(
        title=title,
        status=status,
        detail=detail,
        code=code,
        request_id=request_id,
        errors=list(errors) if errors else None,
    )
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers) if headers else None,
    )
