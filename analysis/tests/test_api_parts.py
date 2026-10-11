"""The service's building blocks, each on its own."""

import asyncio
import json
import logging
import os
from pathlib import Path

import pytest

from analysis.api.contracts import ChangedSymbolsResponse
from analysis.api.logs import JsonFormatter
from analysis.api.middleware import BodyLimitMiddleware
from analysis.api.openapi import DEFAULT_PATH, generate
from analysis.api.settings import Settings, SettingsError
from analysis.api.snapshots import SnapshotNotFound, SnapshotStore
from analysis.cli import main

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "discount"


# --- the contract ---------------------------------------------------------


def test_committed_openapi_document_matches_the_code():
    # If this fails you changed the contract. If that was intended, run
    # `python -m analysis.api.openapi` and review the diff of openapi.json.
    committed = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))

    assert committed == generate()


def test_contract_does_not_depend_on_the_python_version():
    # Python 3.13 renamed the standard phrases for 413 and 422. FastAPI uses
    # those phrases as default descriptions, so every documented response must
    # carry a description of our own.
    from http import HTTPStatus

    phrases = {status.phrase for status in HTTPStatus} | {
        "Request Entity Too Large",
        "Unprocessable Entity",
    }
    for path in generate()["paths"].values():
        for operation in path.values():
            for status, response in operation["responses"].items():
                if status != "200":
                    assert response["description"] not in phrases, (status, response)


def test_errors_are_documented_as_problem_json():
    responses = generate()["paths"]["/v1/changed-symbols"]["post"]["responses"]

    assert set(responses) == {"200", "411", "413", "422", "500"}
    for status in ("411", "413", "422", "500"):
        assert list(responses[status]["content"]) == ["application/problem+json"]


def test_cli_json_output_satisfies_the_same_contract(capsys):
    # The CLI and the service must not drift into two dialects.
    main(
        [
            "changed-symbols",
            "--diff",
            str(EXAMPLE / "change.diff"),
            "--base-dir",
            str(EXAMPLE / "base"),
            "--head-dir",
            str(EXAMPLE / "head"),
            "--format",
            "json",
        ]
    )

    ChangedSymbolsResponse.model_validate_json(capsys.readouterr().out)


# --- snapshots ------------------------------------------------------------


def test_store_opens_a_snapshot_by_name(tmp_path):
    (tmp_path / "abc123").mkdir()
    # Bytes, not text: on Windows, writing text turns "\n" into "\r\n".
    (tmp_path / "abc123" / "mod.py").write_bytes(b"x = 1\n")

    snapshot = SnapshotStore(tmp_path).open("abc123")

    assert snapshot.read("mod.py") == b"x = 1\n"


@pytest.mark.parametrize("snapshot_id", ["missing", "../outside", "a/b", "", ".", "..", "file.txt"])
def test_store_refuses_anything_that_is_not_a_directory_in_the_root(tmp_path, snapshot_id):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    (root / "a").mkdir()
    (root / "a" / "b").mkdir()
    (root / "file.txt").write_text("not a directory")

    with pytest.raises(SnapshotNotFound):
        SnapshotStore(root).open(snapshot_id)


def test_store_refuses_real_directories_whose_names_are_not_valid_ids(tmp_path):
    # These exist and sit directly in the root, so only the name check stops
    # them. A dot-directory such as `.git` or `.cache` is never a snapshot.
    for name in (".hidden", "has space"):
        (tmp_path / name).mkdir()

        with pytest.raises(SnapshotNotFound):
            SnapshotStore(tmp_path).open(name)


def test_store_refuses_a_symlink_that_leaves_the_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    try:
        os.symlink(tmp_path / "outside", root / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")

    with pytest.raises(SnapshotNotFound):
        SnapshotStore(root).open("link")


def test_store_readiness_follows_the_root_directory(tmp_path):
    assert SnapshotStore(tmp_path).is_ready()
    assert not SnapshotStore(tmp_path / "missing").is_ready()


# --- settings -------------------------------------------------------------


def test_settings_defaults():
    settings = Settings.from_env({"BESTTEST_SNAPSHOT_ROOT": "/snapshots"})

    assert settings.snapshot_root == Path("/snapshots")
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.max_request_bytes == 8 * 1024 * 1024


def test_settings_overrides():
    settings = Settings.from_env(
        {
            "BESTTEST_SNAPSHOT_ROOT": "/data",
            "BESTTEST_HOST": "0.0.0.0",
            "BESTTEST_PORT": "9000",
            "BESTTEST_MAX_FILES": "25",
            "BESTTEST_TIME_BUDGET_SECONDS": "2.5",
        }
    )

    assert (settings.host, settings.port) == ("0.0.0.0", 9000)
    assert settings.max_files == 25
    assert settings.time_budget_seconds == 2.5


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"BESTTEST_SNAPSHOT_ROOT": "  "},
        {"BESTTEST_SNAPSHOT_ROOT": "/s", "BESTTEST_PORT": "http"},
        {"BESTTEST_SNAPSHOT_ROOT": "/s", "BESTTEST_MAX_FILES": "0"},
        {"BESTTEST_SNAPSHOT_ROOT": "/s", "BESTTEST_MAX_REQUEST_BYTES": "-1"},
    ],
)
def test_settings_fail_fast_on_bad_configuration(environ):
    # A service that starts with a broken configuration fails later, at a worse
    # moment and with a worse message.
    with pytest.raises(SettingsError):
        Settings.from_env(environ)


# --- body limit, at the ASGI level ----------------------------------------


def call_body_limit(headers: list[tuple[bytes, bytes]], max_bytes: int = 100) -> tuple[int, bool]:
    """Run the middleware with hand-made headers. Returns (status, reached the app)."""
    reached = False
    sent: list[dict] = []

    async def app(scope, receive, send):
        nonlocal reached
        reached = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/", "headers": headers}
    asyncio.run(BodyLimitMiddleware(app, max_bytes)(scope, receive, send))
    return sent[0]["status"], reached


def test_body_limit_lets_small_declared_bodies_through():
    assert call_body_limit([(b"content-length", b"100")]) == (200, True)


def test_body_limit_refuses_large_declared_bodies_without_calling_the_app():
    assert call_body_limit([(b"content-length", b"101")]) == (413, False)


def test_body_limit_refuses_chunked_bodies_even_with_a_small_declared_length():
    # HTTP lets Transfer-Encoding override Content-Length. Trusting the small
    # number here would let an unlimited body through.
    headers = [(b"content-length", b"5"), (b"transfer-encoding", b"chunked")]

    assert call_body_limit(headers) == (411, False)


@pytest.mark.parametrize("value", [b"", b"abc", b"-5", b"1e3"])
def test_body_limit_refuses_lengths_that_are_not_plain_numbers(value):
    assert call_body_limit([(b"content-length", value)]) == (411, False)


# --- log format -----------------------------------------------------------


def test_log_lines_are_json_with_the_extra_fields():
    record = logging.LogRecord("analysis.api", logging.INFO, __file__, 1, "request", None, None)
    record.fields = {"request_id": "abc", "status": 200}

    entry = json.loads(JsonFormatter().format(record))

    assert entry["message"] == "request"
    assert entry["level"] == "info"
    assert (entry["request_id"], entry["status"]) == ("abc", 200)
    assert entry["time"].endswith("+00:00")
