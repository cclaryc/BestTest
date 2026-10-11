"""Check that this machine has what the project needs.

    python scripts/doctor.py

Prints one line per requirement and exits with status 1 if something required
is missing. Uses only the standard library.
"""

from __future__ import annotations

import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRADLE_VERSION = "8.14.3"
GRADLE_RUNS_ON = range(17, 25)  # Java versions that can run this Gradle


def run(*command: str) -> tuple[bool, str]:
    """Run a command; return (succeeded, everything it printed)."""
    if shutil.which(command[0]) is None:
        return False, ""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def first_line(text: str) -> str:
    return text.splitlines()[0].strip() if text else ""


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    results: list[tuple[str, str, str]] = []  # (state, name, detail)

    def report(state: str, name: str, detail: str) -> None:
        results.append((state, name, detail))

    version = sys.version_info
    report(
        "ok" if version >= (3, 12) else "warn",
        "Python",
        f"{version.major}.{version.minor}.{version.micro}"
        + ("" if version >= (3, 12) else " (the analysis service needs 3.12 or newer)"),
    )

    ok, out = run("git", "--version")
    report("ok" if ok else "warn", "Git", first_line(out) or "not found")

    ok, out = run("docker", "--version")
    report(
        "ok" if ok else "MISSING", "Docker", first_line(out) or "not found: install Docker Desktop"
    )
    docker_found = ok

    ok, out = run("docker", "compose", "version")
    report(
        "ok" if ok else "MISSING",
        "Docker Compose",
        first_line(out) or "not found: it comes with Docker Desktop",
    )

    if docker_found:
        ok, out = run("docker", "info", "--format", "{{.ServerVersion}}")
        report(
            "ok" if ok else "MISSING",
            "Docker engine",
            f"running, version {first_line(out)}"
            if ok
            else "not running: start Docker Desktop and wait until it is ready",
        )

    env_file = ROOT / ".env"
    report(
        "ok" if env_file.is_file() else "MISSING",
        ".env file",
        "present" if env_file.is_file() else "missing: copy .env.example to .env",
    )

    # The GitHub App is optional: without it everything except GitHub works.
    client_id = ""
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("BESTTEST_GITHUB_CLIENT_ID="):
                client_id = line.split("=", 1)[1].strip()
    key_file = ROOT / "secrets" / "github-app.pem"
    if not client_id:
        report("info", "GitHub App", "not configured (optional: see docs/milestones/04a)")
    elif not key_file.is_file():
        report("MISSING", "GitHub App", "client id is set, but secrets/github-app.pem is missing")
    else:
        first = key_file.read_text(encoding="ascii", errors="replace").lstrip()[:40]
        looks_right = first.startswith("-----BEGIN RSA PRIVATE KEY-----") or first.startswith(
            "-----BEGIN PRIVATE KEY-----"
        )
        report(
            "ok" if looks_right else "MISSING",
            "GitHub App",
            f"client id {client_id}, private key present"
            if looks_right
            else "secrets/github-app.pem is not a private key file from GitHub",
        )

    for port, purpose in ((8080, "backend"), (5433, "test database")):
        free = port_is_free(port)
        report(
            "ok" if free else "warn",
            f"Port {port}",
            "free" if free else f"in use: the {purpose} wants it (fine if that is already running)",
        )

    # Java is optional: every build and test can run inside Docker.
    ok, out = run("java", "-version")
    match = re.search(r'version "(\d+)', out)
    if not ok or match is None:
        report("info", "Java", "not found (optional: builds and tests can run in Docker)")
    else:
        major = int(match.group(1))
        usable = major in GRADLE_RUNS_ON
        report(
            "ok" if usable else "info",
            "Java",
            f"{major}: "
            + (
                f"can run backend/gradlew (Gradle {GRADLE_VERSION})"
                if usable
                else f"Gradle {GRADLE_VERSION} runs on Java {GRADLE_RUNS_ON.start} to "
                f"{GRADLE_RUNS_ON.stop - 1}; use the Docker commands instead of backend/gradlew"
            ),
        )

    width = max(len(name) for _, name, _ in results)
    for state, name, detail in results:
        print(f"  {state:<7}  {name:<{width}}  {detail}")

    missing = [name for state, name, _ in results if state == "MISSING"]
    print()
    if missing:
        print(f"Not ready. Fix: {', '.join(missing)}.")
        return 1
    print("Ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
