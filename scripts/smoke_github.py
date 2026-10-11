"""Check the GitHub App set-up of the running stack against the real GitHub.

    docker compose up -d
    python scripts/smoke_github.py OWNER/REPO [http://127.0.0.1:8080]

Asks the backend two questions, and the backend asks GitHub:

1. Which GitHub App am I? Proves the client id and the private key.
2. Can I read OWNER/REPO? Proves the App is installed there, and shows the
   short-lived, read-only token the backend obtained for it (never the token
   itself).

Uses only the standard library.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from typing import Any

NEEDED = {"contents": "read", "metadata": "read", "pull_requests": "read"}


class Failure(Exception):
    pass


def call(base_url: str, path: str) -> tuple[int, Any]:
    request = urllib.request.Request(base_url + path, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except (urllib.error.URLError, OSError) as error:
        raise Failure(
            f"the backend at {base_url} cannot be reached ({error}). Is the stack up? docker compose ps"
        ) from None
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


def problem(status: int, body: Any) -> str:
    if isinstance(body, dict) and "code" in body:
        return f"{status} {body.get('code')}: {body.get('detail')} (request id {body.get('request_id')})"
    return f"status {status} with an unexpected body"


ADVICE = {
    "github_authentication_failed": (
        "GitHub rejected the App's credentials. Check that BESTTEST_GITHUB_CLIENT_ID in .env is the\n"
        "        Client ID from the App's settings page, that secrets/github-app.pem is a key of that\n"
        "        same App, and that this computer's clock is right. Then: docker compose up -d"
    ),
    "github_repository_not_accessible": (
        "The App cannot see that repository. On GitHub open the App's page, choose Install App,\n"
        "        and give it access to the repository. Check the spelling of OWNER/REPO too."
    ),
    "github_permission_missing": (
        "On GitHub open the App's settings, Permissions & events, and under Repository permissions\n"
        "        set Contents and Pull requests to Read-only. Then accept the new permissions on the\n"
        "        installation (GitHub emails a link, or see the installation's settings page)."
    ),
    "github_rate_limited": "GitHub asked for a pause. Wait as long as the message says and run this again.",
    "github_unavailable": "GitHub could not be reached from the backend container. Check the internet connection.",
}


def run(repository: str, base_url: str) -> None:
    status, body = call(base_url, "/actuator/health/readiness")
    if status != 200:
        raise Failure(f"the backend is not ready: {problem(status, body)}")
    print("  ok    backend is ready")

    status, body = call(base_url, "/api/github/app")
    if status != 200:
        code = body.get("code") if isinstance(body, dict) else None
        raise Failure(f"asking GitHub which App this is failed: {problem(status, body)}\n        {ADVICE.get(code, '')}")
    if not body.get("configured"):
        raise Failure(
            "no GitHub App is configured. Put the App's Client ID in .env as BESTTEST_GITHUB_CLIENT_ID,\n"
            "        save its private key as secrets/github-app.pem, and run: docker compose up -d"
        )
    app = body["app"]
    granted = app.get("permissions", {})
    print(f"  ok    GitHub knows this backend as the App '{app.get('name')}' (slug {app.get('slug')}, id {app.get('id')})")
    print(f"        permissions granted to the App: {format_permissions(granted)}")
    extra = {name: level for name, level in granted.items() if level != "read" or name not in NEEDED}
    if extra:
        print(f"  note  the App has more than this project needs: {format_permissions(extra)}")

    owner, name = repository.split("/", 1)
    status, body = call(base_url, f"/api/github/repositories/{owner}/{name}")
    if status != 200:
        code = body.get("code") if isinstance(body, dict) else None
        raise Failure(f"reading {repository} failed: {problem(status, body)}\n        {ADVICE.get(code, '')}")
    found, token = body["repository"], body["token"]
    visibility = "private" if found.get("private") else "public"
    print(f"  ok    the App can read {found.get('full_name')} ({visibility}, default branch {found.get('default_branch')})")
    print(f"        installation {body.get('installation_id')}, token valid until {token.get('expires_at')}")
    print(f"        the token may: {format_permissions(token.get('permissions', {}))}")

    may = token.get("permissions", {})
    if any(level != "read" for level in may.values()) or not set(may) <= set(NEEDED):
        raise Failure(f"the token may do more than {format_permissions(NEEDED)}")
    if not {"contents", "pull_requests"} <= set(may):
        raise Failure("the token cannot read contents and pull requests, which the next milestone needs")
    unexpected = set(token) - {"expires_at", "permissions", "repository_selection"}
    if unexpected:
        raise Failure(f"the description of the token has fields it should not have: {sorted(unexpected)}")
    print("  ok    the token is read-only and limited to what is needed")


def format_permissions(permissions: dict[str, str]) -> str:
    return ", ".join(f"{name}: {level}" for name, level in sorted(permissions.items())) or "(none)"


def main() -> int:
    arguments = sys.argv[1:]
    if not arguments or not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", arguments[0]):
        print(__doc__)
        return 2
    base_url = (arguments[1] if len(arguments) > 1 else "http://127.0.0.1:8080").rstrip("/")
    try:
        run(arguments[0], base_url)
    except Failure as failure:
        print(f"  FAIL  {failure}")
        return 1
    print("\nOK: the backend can act as your GitHub App.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
