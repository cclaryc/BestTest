"""Exercise the running stack from outside, the way a client would.

    docker compose up --build -d
    python scripts/smoke_stack.py [http://127.0.0.1:8080]

Sends the bundled example to the backend and follows it all the way through:
backend -> analysis service -> PostgreSQL -> back. Then checks that the two
ways an analysis can go wrong are reported properly. Uses only the standard
library.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

EXAMPLE = Path(__file__).resolve().parent.parent / "analysis" / "examples" / "discount"
EXPECTED_SYMBOLS = {
    "<module>": "modified",
    "clamp": "cosmetic",
    "calculate_discount": "modified",
    "Cart.clear": "added",
}
BASE_COMMIT = "a" * 40
HEAD_COMMIT = "b" * 40


class Failure(Exception):
    pass


def call(base_url: str, method: str, path: str, body: Any = None, request_id: str | None = None):
    """Return (status, parsed JSON body or None, headers)."""
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if request_id is not None:
        headers["X-Request-ID"] = request_id
    request = urllib.request.Request(base_url + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            status, raw, response_headers = response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        status, raw, response_headers = error.code, error.read(), error.headers
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = None
    return status, parsed, response_headers


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def wait_until_ready(base_url: str, seconds: float = 180.0) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            status, body, _ = call(base_url, "GET", "/actuator/health/readiness")
            if status == 200 and body and body.get("status") == "UP":
                return
        except (urllib.error.URLError, OSError):
            pass
        if time.monotonic() > deadline:
            raise Failure(
                f"the backend at {base_url} did not become ready in {seconds:.0f} s. "
                "Look at: docker compose ps, and docker compose logs backend"
            )
        time.sleep(1)


def analysis_request(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "base": {"commit": BASE_COMMIT, "snapshot": "base"},
        "head": {"commit": HEAD_COMMIT, "snapshot": "head"},
        "diff": (EXAMPLE / "change.diff").read_text(encoding="utf-8"),
    }
    body.update(overrides)
    return body


def check_round_trip(base_url: str) -> str:
    status, run, headers = call(
        base_url, "POST", "/api/analyses", analysis_request(), "smoke-stack"
    )
    expect(status == 201, f"POST /api/analyses returned {status}, expected 201: {run}")
    expect(run["status"] == "succeeded", f"the analysis did not succeed: {run.get('error')}")
    expect(headers.get("X-Request-ID") == "smoke-stack", "the request id was not echoed")
    expect(
        headers.get("Location") == f"/api/analyses/{run['id']}",
        f"Location is {headers.get('Location')}",
    )
    summary = (run["file_count"], run["symbol_count"], run["complete"])
    expect(summary == (1, 4, True), f"expected 1 file, 4 symbols, complete; got {summary}")
    symbols = {
        symbol["key"]: symbol["change"]
        for file_change in run["result"]["files"]
        for symbol in file_change["symbols"]
    }
    expect(symbols == EXPECTED_SYMBOLS, f"expected {EXPECTED_SYMBOLS}, got {symbols}")

    status, fetched, _ = call(base_url, "GET", f"/api/analyses/{run['id']}")
    expect(status == 200 and fetched["id"] == run["id"], f"GET by id returned {status}: {fetched}")
    expect(
        fetched["result"] == run["result"],
        "the stored result differs from the one returned at creation",
    )

    status, listed, _ = call(base_url, "GET", "/api/analyses")
    expect(status == 200, f"GET /api/analyses returned {status}")
    mine = [item for item in listed if item["id"] == run["id"]]
    expect(
        len(mine) == 1 and "result" not in mine[0],
        "the list must contain the run, without its result",
    )
    return run["id"]


def check_failed_run(base_url: str) -> None:
    body = analysis_request(head={"commit": HEAD_COMMIT, "snapshot": "no-such-snapshot"})
    status, run, _ = call(base_url, "POST", "/api/analyses", body)
    expect(status == 201, f"a run that fails is still created; got {status}: {run}")
    expect(run["status"] == "failed", f"expected a failed run, got {run['status']}")
    expect(run["error"]["code"] == "snapshot_not_found", f"error is {run.get('error')}")


def check_refusals(base_url: str) -> None:
    status, problem, _ = call(
        base_url,
        "POST",
        "/api/analyses",
        analysis_request(base={"commit": "main", "snapshot": "base"}),
    )
    expect(
        status == 400 and problem and problem.get("code") == "invalid_request",
        f"bad commit: {status} {problem}",
    )
    expect(problem["errors"][0]["location"] == "base.commit", f"errors: {problem.get('errors')}")

    status, problem, _ = call(base_url, "GET", "/api/analyses/00000000-0000-0000-0000-000000000000")
    expect(
        status == 404 and problem and problem.get("code") == "analysis_not_found",
        f"unknown id: {status} {problem}",
    )


def main() -> int:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
    steps = (
        ("backend is ready (database reachable)", lambda: wait_until_ready(base_url)),
        ("analysis runs end to end and is stored", lambda: check_round_trip(base_url)),
        ("a failing analysis is recorded as failed", lambda: check_failed_run(base_url)),
        ("bad requests are refused with a clear error", lambda: check_refusals(base_url)),
    )
    for description, step in steps:
        try:
            step()
        except Failure as failure:
            print(f"  FAIL  {description}\n        {failure}")
            return 1
        except (urllib.error.URLError, OSError, KeyError, TypeError) as error:
            print(f"  FAIL  {description}\n        {type(error).__name__}: {error}")
            return 1
        print(f"  ok    {description}")
    print("\nOK: the whole stack works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
