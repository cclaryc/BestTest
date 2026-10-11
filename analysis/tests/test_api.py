"""The HTTP service, exercised in-process through FastAPI's test client."""

import json
import logging
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import analysis.api.app as app_module
from analysis import __version__
from analysis.api import Settings, create_app
from analysis.api.contracts import ChangedSymbolsResponse, Problem
from analysis.model import SkipReason

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "discount"
BASE_COMMIT = "a" * 40
HEAD_COMMIT = "b" * 40
PROBLEM = "application/problem+json"
URL = "/v1/changed-symbols"


@pytest.fixture
def snapshot_root(tmp_path: Path) -> Path:
    """A snapshot directory holding the example as snapshots ``base`` and ``head``."""
    root = tmp_path / "snapshots"
    shutil.copytree(EXAMPLE / "base", root / "base")
    shutil.copytree(EXAMPLE / "head", root / "head")
    return root


@pytest.fixture
def client(snapshot_root: Path) -> TestClient:
    return TestClient(create_app(Settings(snapshot_root=snapshot_root)))


def request_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "base": {"commit": BASE_COMMIT, "snapshot": "base"},
        "head": {"commit": HEAD_COMMIT, "snapshot": "head"},
        "diff": (EXAMPLE / "change.diff").read_text(encoding="utf-8"),
    }
    body.update(overrides)
    return body


def problem_of(response) -> Problem:
    """Parse an error response, checking what every error must have in common."""
    assert response.headers["content-type"] == PROBLEM
    problem = Problem.model_validate(response.json())
    assert problem.status == response.status_code
    assert problem.request_id == response.headers["x-request-id"]
    return problem


# --- the happy path -------------------------------------------------------


def test_changed_symbols_for_the_example(client):
    response = client.post(URL, json=request_body())

    assert response.status_code == 200
    result = ChangedSymbolsResponse.model_validate(response.json())
    assert result.complete
    (file_change,) = result.files
    assert file_change.path == "shop/pricing.py"
    assert {symbol.key: symbol.change.value for symbol in file_change.symbols} == {
        "<module>": "modified",
        "clamp": "cosmetic",
        "calculate_discount": "modified",
        "Cart.clear": "added",
    }


def test_response_for_the_example_matches_the_shared_fixture(client):
    # examples/discount/response.json is read by the backend's tests as "what
    # the analysis service really returns". This test is what makes that true.
    # If it fails after an intended change, regenerate the file from the
    # response and re-run the backend's tests.
    expected = json.loads((EXAMPLE / "response.json").read_text(encoding="utf-8"))

    response = client.post(URL, json=request_body())

    assert response.json() == expected


def test_empty_diff_is_a_valid_request_with_no_files(client):
    response = client.post(URL, json=request_body(diff=""))

    assert response.status_code == 200
    assert response.json() == {"complete": True, "files": []}


def test_health_reports_the_version(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_ready_when_the_snapshot_directory_exists(client):
    assert client.get("/readyz").status_code == 200


def test_not_ready_when_the_snapshot_directory_is_missing(tmp_path):
    client = TestClient(create_app(Settings(snapshot_root=tmp_path / "missing")))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert problem_of(response).code == "not_ready"
    # Alive and ready are different questions: the process itself is fine.
    assert client.get("/healthz").status_code == 200


# --- requests the service refuses -----------------------------------------


def test_unknown_snapshot(client):
    body = request_body(head={"commit": HEAD_COMMIT, "snapshot": "no-such-snapshot"})

    response = client.post(URL, json=body)

    assert response.status_code == 422
    problem = problem_of(response)
    assert problem.code == "snapshot_not_found"
    assert "no-such-snapshot" in (problem.detail or "")


@pytest.mark.parametrize(
    "snapshot",
    ["../base", "base/../head", "/etc", "C:\\Windows", ".", "..", ".hidden", "", "a" * 129, "a b"],
)
def test_snapshot_ids_that_are_not_plain_names_are_rejected(client, snapshot):
    body = request_body(base={"commit": BASE_COMMIT, "snapshot": snapshot})

    response = client.post(URL, json=body)

    assert response.status_code == 422
    problem = problem_of(response)
    assert problem.code == "invalid_request"
    assert [error.location for error in problem.errors or []] == ["body.base.snapshot"]


@pytest.mark.parametrize("commit", ["main", "abc123", "A" * 40, "g" * 40, "a" * 41])
def test_commit_must_be_a_full_hash(client, commit):
    response = client.post(URL, json=request_body(base={"commit": commit, "snapshot": "base"}))

    assert response.status_code == 422
    assert problem_of(response).code == "invalid_request"


def test_unknown_fields_are_rejected(client):
    response = client.post(URL, json=request_body(dif="typo"))

    assert response.status_code == 422
    assert [error.location for error in problem_of(response).errors or []] == ["body.dif"]


def test_missing_fields_are_listed(client):
    response = client.post(URL, json={"diff": ""})

    locations = {error.location for error in problem_of(response).errors or []}
    assert response.status_code == 422
    assert locations == {"body.base", "body.head"}


def test_body_that_is_not_json(client):
    response = client.post(URL, content=b"{not json", headers={"content-type": "application/json"})

    assert response.status_code == 422
    assert problem_of(response).code == "invalid_request"


def test_malformed_diff(client):
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n-b\n-c\n+d\n"

    response = client.post(URL, json=request_body(diff=diff))

    assert response.status_code == 422
    assert problem_of(response).code == "invalid_diff"


def test_validation_errors_do_not_echo_the_request(client):
    # Pydantic's own error format includes the rejected input. Here that could
    # be a whole diff, repeated in the response and in anything that logs it.
    secret = "TOP-SECRET-LINE"
    body = request_body(diff=["not a string", secret])

    response = client.post(URL, json=body)

    assert response.status_code == 422
    assert secret not in response.text


def test_unknown_path_and_wrong_method_use_the_same_error_format(client):
    not_found = client.get("/v1/nothing-here")
    wrong_method = client.get(URL)

    assert (not_found.status_code, problem_of(not_found).code) == (404, "not_found")
    assert (wrong_method.status_code, problem_of(wrong_method).code) == (405, "method_not_allowed")
    assert wrong_method.headers["allow"] == "POST"


# --- limits ---------------------------------------------------------------


def test_request_over_the_size_limit_is_refused(snapshot_root):
    client = TestClient(create_app(Settings(snapshot_root=snapshot_root, max_request_bytes=500)))

    response = client.post(URL, json=request_body())

    assert response.status_code == 413
    assert problem_of(response).code == "request_too_large"


def test_request_without_a_declared_length_is_refused(client):
    def chunks():
        yield json.dumps(request_body()).encode()

    # A generator body has no known length, so the client sends it chunked.
    response = client.post(URL, content=chunks(), headers={"content-type": "application/json"})

    assert response.status_code == 411
    assert problem_of(response).code == "length_required"


def test_file_limit_marks_the_result_incomplete(snapshot_root):
    (snapshot_root / "base" / "extra.py").write_text("x = 1\n")
    (snapshot_root / "head" / "extra.py").write_text("x = 2\n")
    diff = (EXAMPLE / "change.diff").read_text(encoding="utf-8") + (
        "diff --git a/extra.py b/extra.py\n"
        "--- a/extra.py\n"
        "+++ b/extra.py\n"
        "@@ -1 +1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )
    client = TestClient(create_app(Settings(snapshot_root=snapshot_root, max_files=1)))

    result = ChangedSymbolsResponse.model_validate(
        client.post(URL, json=request_body(diff=diff)).json()
    )

    assert not result.complete
    assert [file_change.skipped for file_change in result.files] == [
        None,
        SkipReason.TOO_MANY_FILES,
    ]


# --- request ids, logging, crashes ----------------------------------------


def test_request_id_is_echoed(client):
    response = client.get("/healthz", headers={"X-Request-ID": "job-42.stage-1"})

    assert response.headers["x-request-id"] == "job-42.stage-1"


@pytest.mark.parametrize("supplied", ["has space", "x" * 65, "semi;colon", "new\tline"])
def test_unusable_request_id_is_replaced(client, supplied):
    response = client.get("/healthz", headers={"X-Request-ID": supplied})

    generated = response.headers["x-request-id"]
    assert generated != supplied
    assert len(generated) == 32 and generated.isalnum()


def test_request_id_appears_in_error_bodies(client):
    response = client.post(URL, json={}, headers={"X-Request-ID": "trace-me"})

    assert problem_of(response).request_id == "trace-me"


def test_each_request_is_logged_once_without_its_content(client, caplog):
    with caplog.at_level(logging.INFO, logger="analysis"):
        client.post(URL, json=request_body(), headers={"X-Request-ID": "log-test"})

    request_logs = [record for record in caplog.records if record.getMessage() == "request"]
    assert len(request_logs) == 1
    fields = request_logs[0].fields
    assert fields["request_id"] == "log-test"
    assert (fields["method"], fields["path"], fields["status"]) == ("POST", URL, 200)
    assert fields["duration_ms"] >= 0

    everything_logged = " ".join(
        f"{record.getMessage()} {getattr(record, 'fields', '')}" for record in caplog.records
    )
    assert "calculate_discount" not in everything_logged
    assert "MAX_DISCOUNT" not in everything_logged


def test_healthy_probes_stay_out_of_the_normal_log(client, tmp_path, caplog):
    not_ready = TestClient(create_app(Settings(snapshot_root=tmp_path / "missing")))

    with caplog.at_level(logging.INFO, logger="analysis"):
        client.get("/healthz")
        client.get("/readyz")
        not_ready.get("/readyz")

    logged = [(r.fields["path"], r.fields["status"]) for r in caplog.records if r.msg == "request"]
    assert logged == [("/readyz", 503)]


def test_a_crash_becomes_a_500_that_reveals_nothing(client, caplog, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("database password is hunter2")

    monkeypatch.setattr(app_module, "detect_changed_symbols", explode)

    with caplog.at_level(logging.ERROR, logger="analysis"):
        response = client.post(URL, json=request_body(), headers={"X-Request-ID": "crash-1"})

    assert response.status_code == 500
    problem = problem_of(response)
    assert problem.code == "internal_error"
    assert problem.request_id == "crash-1"
    assert "hunter2" not in response.text
    # The details are kept, but for us: in the log, findable by the request id.
    (record,) = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert record.fields["request_id"] == "crash-1"
    assert record.exc_info is not None
