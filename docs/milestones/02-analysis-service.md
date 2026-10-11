# Milestone 2: the analysis service

The change-detection library from Milestone 1 is now an HTTP service. The
backend will send it a diff and the names of two repository snapshots, and get
back the changed symbols as JSON that follows a written contract.

Status: done. 186 tests pass on Linux (75 of them new). The container image
was developed on a stand-in base image, because Docker Hub is not reachable from
the machine this was written on. It was first built on the real
`python:3.12-slim` image on 2026-10-12, and runs as part of the Milestone 3
stack.

## What it does

```http
POST /v1/changed-symbols
Content-Type: application/json

{
  "base": {"commit": "<40 hex>", "snapshot": "base"},
  "head": {"commit": "<40 hex>", "snapshot": "head"},
  "diff": "diff --git a/shop/pricing.py b/shop/pricing.py\n..."
}
```

```json
{
  "complete": true,
  "files": [
    {
      "path": "shop/pricing.py",
      "status": "modified",
      "language": "python",
      "skipped": null,
      "syntax_errors": false,
      "symbols": [
        {"key": "calculate_discount", "kind": "function", "change": "modified",
         "parts": ["signature", "body"], "...": "..."}
      ]
    }
  ]
}
```

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/changed-symbols` | The analysis |
| `GET /healthz` | Is the process alive? |
| `GET /readyz` | Can it do its job right now? (Is the snapshot directory there?) |
| `GET /docs` | Interactive API page, generated from the contract |
| `GET /openapi.json` | The contract itself |

## Run it

From the `analysis` folder, in PowerShell. The first command picks up the new
dependencies:

```powershell
.venv\Scripts\python -m pip install -e ".[dev]" -c requirements-dev.lock
.venv\Scripts\python -m pytest
$env:BESTTEST_SNAPSHOT_ROOT = "examples\discount"
.venv\Scripts\python -m analysis.api
```

Leave that running. In a second PowerShell window, also in `analysis`:

```powershell
.venv\Scripts\python scripts\smoke.py
```

It sends the example to the running service and ends with
`OK: the service returned the expected symbols.` Then open
<http://127.0.0.1:8000/docs> in a browser and try a request by hand, including
a wrong one, to see the error format.

With Docker, from the repository root:

```powershell
docker build -t besttest-analysis analysis
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges -v "${PWD}\analysis\examples\discount:/snapshots:ro" -p 127.0.0.1:8000:8000 besttest-analysis
```

and run `scripts\smoke.py` against it in the same way.

## How a request flows

| Step | What happens | Code |
| --- | --- | --- |
| 1 | The request gets an id; a timer starts | `api/middleware.py` |
| 2 | A body that is too large, or has no declared size, is refused unread | `api/middleware.py` |
| 3 | The JSON is checked against the contract | `api/contracts.py` |
| 4 | The two snapshot names are resolved to directories | `api/snapshots.py` |
| 5 | The diff is parsed and the symbols classified, within limits | `symbols/changed.py` |
| 6 | The result is converted to the response model | `api/contracts.py` |
| 7 | One log line records what happened, without the content | `api/middleware.py` |

Steps 4 to 6 are the endpoint function in `api/app.py`, which is under fifty
lines. Everything interesting about the analysis still lives in the library.

## Concepts behind it

### The contract is code, and it is checked in

The request and response are Pydantic models. FastAPI validates every request
against them and generates an OpenAPI document from them, so the documentation
cannot disagree with the behaviour: they are the same thing.

A copy of that document, `analysis/openapi.json`, is committed. A test fails
when the code and the file differ. This has two effects. A contract change
cannot slip in unnoticed, because it appears in code review as a diff of that
file. And the Kotlin backend can build its client from the file without running
this service.

Unknown fields in a request are rejected. A caller who writes `"dif"` instead
of `"diff"` gets an error naming the field, not a puzzling empty result.

### Snapshots travel by name, not by value

The request does not contain source code. The backend unpacks each version of
the repository into a directory on a shared volume and sends the directory's
name. Three things follow:

- Requests stay small. A diff is kilobytes; a repository is not.
- The service needs no GitHub token. It cannot leak what it never has.
- The service is stateless. Any copy of it can answer any request, and a
  request can be retried safely.

A snapshot name is checked twice: by a pattern in the contract (letters, digits,
dot, dash, underscore, starting with a letter or digit) and again where it meets
the file system, where the resolved path must be a directory directly inside
the snapshot root. `../etc`, an absolute path, or a symlink pointing elsewhere
all fail.

### Why the endpoint is `def` and not `async def`

FastAPI runs on an event loop: one thread that switches between requests
whenever one of them waits for the network. That works as long as nobody keeps
the thread busy. Parsing code is pure computation and never waits, so an
`async def` endpoint doing it would freeze every other request, health checks
included, until it finished. A container orchestrator would then see failed
health checks and kill a service that was merely working.

Declared as a plain `def`, the endpoint runs on a worker thread and the event
loop stays free. Measured on a request that took 13.5 seconds (120 files of
4,038 lines each, both versions parsed):

| `/healthz` response time | Median | Slowest |
| --- | --- | --- |
| Service idle | 1.3 ms | 27 ms |
| During the 13.5 s request | 11 ms | 53 ms |

What threads do not give is speed. Python runs one thread of Python code at a
time (the global interpreter lock), so two analyses in one process take turns.
Real parallelism needs several processes, which the stateless design allows
without any code change. That is deferred until a measurement asks for it.

### Alive is not the same as ready

`/healthz` answers "is the process running?". `/readyz` answers "can it serve
requests?", which here means the snapshot directory exists. They are separate
because the right reaction differs: a process that is not alive should be
restarted, while one that is alive but not ready should simply get no traffic
until its volume appears. The container's health check uses `/readyz`.

### One error format

Every error, whether a bad request, an unknown URL or a crash, has the same
shape, the standard "problem details" format (RFC 9457):

```json
{
  "type": "about:blank",
  "title": "Snapshot not found",
  "status": 422,
  "detail": "No snapshot named 'nope' exists.",
  "code": "snapshot_not_found",
  "request_id": "3f1c..."
}
```

`code` is for programs, `detail` for people. Spring has a built-in class for
this format, so the backend can read errors without custom parsing.

Two rules about what an error may contain:

- A validation error names the field and the reason, never the rejected value.
  The value could be an entire diff, which would then be copied into the
  response and into every log that records it.
- A crash returns a fixed sentence and the request id. The exception text goes
  to the log only. Internal messages can contain paths, queries or secrets.

### Limits, and saying so when they bite

The input is a diff of someone else's code, so its size is not ours to choose.

| Limit | Default | What happens beyond it |
| --- | --- | --- |
| Request body | 8 MiB | Refused with 413 before the body is read |
| One file | 1 MB | That file is skipped: `too_large` |
| Files parsed per request | 1,000 | The rest are skipped: `too_many_files` |
| Time per request | 30 s | The rest are skipped: `time_budget_exceeded` |

When a limit cuts work short, the response still succeeds, lists every skipped
file with its reason, and sets `complete` to `false`. A caller must read
`complete: false` as "anything in the skipped files may have changed", never as
"nothing else changed". Returning a partial answer that looks whole would be
the worst outcome: test selection would skip tests on the strength of code
nobody examined.

The body limit relies on the `Content-Length` header, which the web server
enforces. A chunked body has no declared size, and HTTP lets it override
`Content-Length` when both are present, so chunked bodies are refused outright.

### Request ids and logs

Each request carries an id, taken from the `X-Request-ID` header when the
caller sends a short, plain one, and generated otherwise. It is returned in the
response, written in every log line for that request, and included in error
bodies. When something fails across two services, that id is how the two logs
are joined.

Logs are one JSON object per line: time, level, message, request id, method,
path, status, duration. Diff text and source code are never logged, and a test
checks that. Healthy probe requests are kept out of the normal log, since one
arrives every few seconds and says nothing new.

### The container

- **Two stages.** The first installs dependencies into a virtual environment;
  the second copies only that environment. pip is removed at the end.
- **Not root.** The process runs as user 10001. A process that does not need
  root should not have it, so a bug in it cannot do root's damage.
- **Read-only.** The service writes nothing to disk, so the container runs with
  a read-only file system and the snapshots mounted read-only.
- **Pinned versions.** `pyproject.toml` says which versions are acceptable;
  `requirements.lock` records the exact set that was tested. The image installs
  the exact set, so the same commit always builds the same image.
- **Layer order.** Dependencies are installed before the source is copied.
  Docker reuses unchanged layers, so editing code does not download packages
  again.

## Decisions and their trade-offs

| Decision | Alternative | Why this way |
| --- | --- | --- |
| Snapshots by name on a shared volume | Send file contents in the request | Small requests, no credentials in the service, no state. The cost is that both services must see the same volume. |
| One endpoint per analysis stage | One endpoint that does everything | The backend owns progress and retries, so it needs to call stages one at a time. See `docs/adr/0002`. |
| Partial result plus `complete: false` | Fail the whole request when a limit is hit | A pull request with 3,000 files should still get analysis for the files that fit. |
| 422 for an unknown snapshot | 404 | 404 would be indistinguishable from a mistyped URL. The endpoint exists; the request refers to something that does not. |
| No authentication | A shared secret header | The service is internal and listens on loopback by default. A secret adds a credential to manage and little protection inside one deployment. Revisit if it is ever exposed. |
| Settings from environment variables, read by hand | A settings library | Seven values. One fewer dependency, and a bad value stops start-up with a clear message. |
| Exact pins in a lock file, generated with pip | A lock tool such as uv or pip-tools | No new tool to learn yet. The cost is no hash checking, which those tools add. |

## Evidence

**Tests.** 186 in total, 75 new. The new ones cover the endpoint (success,
every refusal, limits), the error format, request ids, logging, snapshot
resolution, settings, the body limit at the protocol level, and the contract
file. They ran on Linux with Python 3.12 (from a clean copy, with the pinned
versions, the way CI will) and with Python 3.13. The first run on Windows (Python 3.12) passed all but one: a test wrote a file
in text mode, which on Windows changes the line endings, and then compared
bytes. The test was wrong, not the service, and now writes bytes.

**Tests of the tests.** The service was broken on purpose in 19 ways, one at a
time: the size limit off by one, chunked bodies allowed, crash details leaked,
the path check removed, the diff written to the log, and so on. 18 failed a
test immediately. One did not (removing the snapshot name check, because a
second check caught the same inputs), which showed a missing test for
directories that exist but have invalid names.

**A real server.** Started with `python -m analysis.api`, called over HTTP by
`scripts/smoke.py`, which checks the answer.

**The container.** Built from the Dockerfile and run with a read-only file
system, all capabilities dropped and no privilege escalation. It answered the
smoke test, ran as uid 10001, reported healthy, reported unhealthy when started
without a snapshot volume, and stopped cleanly in 0.3 s. The base image was a
local stand-in made from Ubuntu 24.04 with Python 3.12, not `python:3.12-slim`.

## A bug found along the way

The contract test passed on Python 3.13 and failed on 3.12, with identical
library versions. The cause: for each documented error response, FastAPI fills
in the standard phrase for the status code, and Python 3.13 renamed two of them
(413 became "Content Too Large", 422 became "Unprocessable Content"). The
checked-in contract therefore depended on which Python had generated it.

It was caught only because the full CI sequence was repeated in a fresh copy on
the other Python version before delivery. Every documented response now has a
description of its own, and a test fails if one ever falls back to a standard
phrase.

The lesson: "works on my machine" includes "works on my Python version". A
check that is meant to run in CI should be run the way CI runs it at least once
before trusting it.

## Not verified yet

- The image build on the real `python:3.12-slim` base.
- The CI workflow. It is in `ci/analysis.yml` and has never run.

## Known limits

Added to `docs/limitations.md`. The main ones:

- No authentication. Safety depends on the service not being reachable from
  outside the deployment.
- The time budget is checked between files, so one very slow file can overrun.
- One process analyses one request at a time at full speed; concurrent
  requests share a single core.

## Questions to be able to answer

1. Why does the request carry a snapshot name and not the files themselves?
2. What exactly could go wrong if a snapshot name were used as a path without
   checks, and which two checks prevent it?
3. Why is the endpoint a plain `def`? What would break with `async def`, and
   what does a plain `def` still not give you?
4. What is the difference between liveness and readiness, and why does the
   container health check use readiness?
5. A request hits the file limit. Why is returning 200 with `complete: false`
   better than returning an error? What must the caller do with it?
6. Why must a validation error not include the rejected value?
7. Why are chunked request bodies refused when `Content-Length` is checked
   anyway?
8. What is the difference between the version ranges in `pyproject.toml` and
   the pins in `requirements.lock`? Who uses which?
9. Why is `openapi.json` committed when the service can generate it on request?

## Next

Milestone 3 is the backend skeleton: Kotlin, Spring Boot, PostgreSQL with
Flyway, a client for this service checked against `openapi.json`, and one
Compose file that starts everything.
