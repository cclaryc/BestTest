# BestTest

An AI-assisted code review and test selection platform for GitHub pull requests.
It works out which code a change really affects, which tests are worth running,
and where a regression test is missing, using static analysis first and a
language model second.

This is not a wrapper that sends a diff to a model. The model only sees what the
analysis has already established, and every finding must point at real code.

## Status

Milestones 1 to 3 of 21 are done. The project is built in small steps, each
with tests and a write-up.

| # | Milestone | State |
| --- | --- | --- |
| 1 | Changed-symbol detection for Python, as a library and CLI | Done |
| 2 | Analysis service (FastAPI) with a checked-in API contract and a container image | Done |
| 3 | Backend skeleton (Kotlin, Spring Boot, PostgreSQL) and one Compose file for the stack | Done |
| 4 | GitHub App integration | |
| 5 | Job pipeline with live progress | |
| 6 | Model review with validated findings | |
| 7 | Web dashboard | |

Milestones 8 to 21 cover the dependency and call graphs, test selection and its
benchmark, Java support, the chat assistant, sandboxed test runs, and
observability.

## What works today

```text
$ python -m analysis changed-symbols --diff examples/discount/change.diff \
    --base-dir examples/discount/base --head-dir examples/discount/head

shop/pricing.py (modified)
  M  module    <module>            top-level code  [body]
  c  function  clamp               lines 6-8
  M  function  calculate_discount  lines 11-14  [signature, body]
  A  method    Cart.clear          lines 24-25

A added  D deleted  M modified  c cosmetic (comments or layout only)
```

Checked against CPython's own parser on 900 commits of click, requests and
flask: 107,406 symbols compared, no real change missed. See
[`benchmarks/changed_symbols`](benchmarks/changed_symbols/README.md).

The same analysis is available over HTTP as `POST /v1/changed-symbols`. The
contract is [`analysis/openapi.json`](analysis/openapi.json).

## Repository layout

| Path | Contents |
| --- | --- |
| [`analysis/`](analysis/README.md) | Python: parsing, change detection, later graphs, test selection and model calls |
| [`backend/`](backend/README.md) | Kotlin and Spring Boot: stores analyses, calls the analysis service; later GitHub, sign-in and jobs |
| `compose.yaml` | Starts PostgreSQL, the analysis service and the backend together |
| `scripts/` | `doctor.py` checks your machine; `smoke_stack.py` tests the running stack |
| [`benchmarks/`](benchmarks/changed_symbols/README.md) | Reproducible measurements and their raw results |
| [`docs/milestones/`](docs/milestones/) | What each milestone built, how it works and why |
| [`docs/adr/`](docs/adr/) | Architecture decisions and their trade-offs |
| [`docs/limitations.md`](docs/limitations.md) | What the analysis cannot do |

The web dashboard and sandbox runner get their own directories in the
milestones that introduce them.

## Getting started

Run `python scripts/doctor.py` to check your machine. Then see
[`analysis/README.md`](analysis/README.md) for the analysis service alone, or
[`backend/README.md`](backend/README.md) for the whole stack.
