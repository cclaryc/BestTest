# Benchmark: changed-symbol detection against an independent oracle

`oracle.py` replays a repository's recent commits and asks two unrelated
implementations which Python symbols each commit changed:

- **ours**: Tree-sitter syntax trees and fingerprints (the `analysis` package);
- **the oracle**: CPython's own parser, comparing `ast.dump` output per symbol.

They share no parsing code. Every symbol in every changed Python file is
compared, and each disagreement is one of two kinds:

- **reported only by us**: we say modified, the oracle says unchanged. `ast`
  discards more than we do (quote style, trailing commas, redundant
  parentheses), so this is expected and errs in the safe direction.
- **missed by us**: the oracle sees a change and we do not. This would be a bug.

## Results

Run on 2026-10-10 with Python 3.13.16, tree-sitter 0.26.0 and
tree-sitter-python 0.25.0, over the last 300 non-merge commits that touch a
`.py` file in each repository.

| Repository | At commit | Files | Symbols compared | Changed, both agree | Reported only by us | Missed by us |
| --- | --- | --- | --- | --- | --- | --- |
| pallets/click | `2247b35` | 688 | 47,476 | 2,673 | 16 | 0 |
| psf/requests | `611c616` | 554 | 28,791 | 1,167 | 383 | 0 |
| pallets/flask | `d086db85` | 686 | 31,139 | 2,149 | 13 | 0 |
| **Total** | | 1,928 | 107,406 | 5,989 | 412 | 0 |

Of the 383 over-reports in requests, 374 come from one commit, `2a6f290`
("Add automatic code formatting to Requests"), which rewrote quote styles across
the code base.

The raw output of each run, with example disagreements, is in `results/`.

Time per commit, covering the git calls, parsing both versions of every changed
file and classification, had a median between 0.04 s and 0.1 s. The three runs
shared one machine, so treat this as an order of magnitude, not a measurement.

## What this does and does not show

It shows that, on this sample, the tool never called a symbol unchanged when
CPython's parser says its code differs, and that the over-reports are rare
outside formatter commits.

It does not show that these are the right symbols for choosing tests. That
needs a ground truth based on test coverage, which arrives with the test
selection benchmark in Milestone 11. It also covers only code that the running
Python version can parse, and only files that exist on both sides of a commit.

## Reproduce

```bash
git clone --depth 700 --single-branch https://github.com/pallets/click
cd BestTest/analysis && python -m venv .venv && .venv/bin/python -m pip install -e .
.venv/bin/python ../benchmarks/changed_symbols/oracle.py --repo ../../click --commits 300
```

The script exits with status 1 if anything is missed, so it can gate CI later.
Numbers will differ once the repositories gain new commits; check out the
commits in the table to repeat this run exactly.
