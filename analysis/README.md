# analysis

The static analysis core of BestTest, in Python. It will grow into the FastAPI
analysis service. Today it does one thing: given a diff and both versions of the
code, it reports which functions, methods and classes changed.

## Set up and test

Python 3.12 or newer.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"     # Windows: .venv\Scripts\python
.venv/bin/python -m pytest
.venv/bin/python -m ruff check . && .venv/bin/python -m mypy
```

## Use

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

`--format json` prints the structured form. `--no-merge-base` compares the two
revisions directly instead of from their common ancestor.

As a library:

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
| `src/analysis/cli.py` | Command-line entry point |
| `examples/discount/` | A small change used in the docs and the tests |

Imports point one way: `model` is used by everything, `symbols` uses `diff`,
`parsing` and `sources`, and nothing below imports `symbols`.

How it works and why: `../docs/milestones/01-changed-symbols.md`.
