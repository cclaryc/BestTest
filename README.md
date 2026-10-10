# BestTest

An AI-assisted code review and test selection platform for GitHub pull requests.
It works out which code a change really affects, which tests are worth running,
and where a regression test is missing, using static analysis first and a
language model second.

This is not a wrapper that sends a diff to a model. The model only sees what the
analysis has already established, and every finding must point at real code.

## Status

Milestone 1 of 21 is done. The project is built in small steps, each with tests
and a write-up.

| # | Milestone | State |
| --- | --- | --- |
| 1 | Changed-symbol detection for Python, as a library and CLI | Done |
| 2 | Analysis service (FastAPI) | Next |
| 3 | Backend skeleton (Kotlin, Spring Boot, PostgreSQL) | |
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

## Repository layout

| Path | Contents |
| --- | --- |
| [`analysis/`](analysis/README.md) | Python: parsing, change detection, later graphs, test selection and model calls |
| [`benchmarks/`](benchmarks/changed_symbols/README.md) | Reproducible measurements and their raw results |
| [`docs/milestones/`](docs/milestones/01-changed-symbols.md) | What each milestone built, how it works and why |
| [`docs/adr/`](docs/adr/0001-classify-changes-by-fingerprint.md) | Architecture decisions and their trade-offs |
| [`docs/limitations.md`](docs/limitations.md) | What the analysis cannot do |

The backend, web dashboard and sandbox runner get their own directories in the
milestones that introduce them.

## Getting started

See [`analysis/README.md`](analysis/README.md).
