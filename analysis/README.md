# analysis

The analysis service of BestTest, in Python. Given a diff and both versions of
the code, it reports which functions, methods and classes changed. It can be
used three ways: as an HTTP service, from the command line, or as a library.

## Set up and test

Python 3.12 or newer.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]" -c requirements-dev.lock   # Windows: .venv\Scripts\python
.venv/bin/python -m pytest
.venv/bin/python -m ruff check . && .venv/bin/python -m mypy
```

`-c requirements-dev.lock` installs the exact versions the project was tested
with. Leave it out to get the newest versions `pyproject.toml` allows.

## Run the service

```bash
BESTTEST_SNAPSHOT_ROOT=examples/discount python -m analysis.api
python scripts/smoke.py          # in another terminal: calls it and checks the answer
```

In PowerShell, set the variable first: `$env:BESTTEST_SNAPSHOT_ROOT = "examples\discount"`.

Interactive API page: <http://127.0.0.1:8000/docs>.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BESTTEST_SNAPSHOT_ROOT` | required | Directory whose sub-directories are repository snapshots |
| `BESTTEST_HOST` | `127.0.0.1` | Address to listen on (`0.0.0.0` inside the container) |
| `BESTTEST_PORT` | `8000` | Port to listen on |
| `BESTTEST_MAX_REQUEST_BYTES` | `8388608` | Largest request body accepted |
| `BESTTEST_MAX_FILE_BYTES` | `1000000` | Larger files are skipped |
| `BESTTEST_MAX_FILES` | `1000` | Files parsed per request before the rest are skipped |
| `BESTTEST_TIME_BUDGET_SECONDS` | `30` | Time per request before the rest are skipped |

As a container, from the repository root:

```bash
docker build -t besttest-analysis analysis
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  -v "$PWD/analysis/examples/discount:/snapshots:ro" -p 127.0.0.1:8000:8000 besttest-analysis
```

The service has no authentication. Keep it on a private network.

## Change the contract

The request and response models are in `src/analysis/api/contracts.py`. After
changing them, regenerate the checked-in OpenAPI document and review its diff:

```bash
python -m analysis.api.openapi
```

A test fails while the code and `openapi.json` disagree.

## Command line

From a diff file and two directories (no git needed):

```bash
python -m analysis changed-symbols \
  --diff examples/discount/change.diff \
  --base-dir examples/discount/base \
  --head-dir examples/discount/head
```

From a git repository, the way a pull request is measured:

```bash
python -m analysis changed-symbols --repo /path/to/repo --base main --head my-branch
```

`--format json` prints the same structure the service returns. `--no-merge-base`
compares the two revisions directly instead of from their common ancestor.

## Library

```python
from analysis import detect_changed_symbols
from analysis.diff import parse_unified_diff
from analysis.sources import GitSnapshot, git_diff

base, head = GitSnapshot(repo, "main"), GitSnapshot(repo, "my-branch")
changes = detect_changed_symbols(
    parse_unified_diff(git_diff(repo, "main", "my-branch")), base, head
)
```

## Layout

| Path | Responsibility |
| --- | --- |
| `src/analysis/model.py` | Records shared by every stage: `Symbol`, `ChangedSymbol`, `FileChange` |
| `src/analysis/diff/` | Unified diff text to `FileDiff` records |
| `src/analysis/sources.py` | Reading file versions from git, a directory or memory, safely |
| `src/analysis/parsing/` | Tree-sitter, the per-language adapter, structural fingerprints |
| `src/analysis/symbols/` | Pairing symbols across versions and classifying the change |
| `src/analysis/cli.py` | Command-line front end |
| `src/analysis/api/` | HTTP front end: contract, endpoint, errors, limits, logging |
| `openapi.json` | The HTTP contract, generated from the code and checked in |
| `requirements.lock`, `requirements-dev.lock` | Exact tested versions; regenerate with `scripts/lock.py` |
| `Dockerfile` | Container image for the service |
| `scripts/smoke.py` | Calls a running service with the example and checks the answer |
| `examples/discount/` | A small change used in the docs and the tests; `response.json` is the service's answer for it, shared with the backend's tests |

Imports point one way. `model` is used by everything; `symbols` uses `diff`,
`parsing` and `sources`; `cli` and `api` sit on top and do not import each
other. A test enforces this.

How it works and why: `../docs/milestones/`.
