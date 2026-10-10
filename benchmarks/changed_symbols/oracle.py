"""Check changed-symbol detection against an independent oracle.

For every commit in a repository's recent history, this script asks two
unrelated implementations which Python symbols the commit changed:

* ours: Tree-sitter syntax trees plus fingerprints (``analysis`` package);
* the oracle: CPython's own parser (``ast``), comparing ``ast.dump`` output.

The two share no parsing code, so agreement is real evidence. Disagreements fall
into two groups with very different meanings:

* ``extra``: we say modified, the oracle says unchanged. Expected and harmless.
  ``ast`` normalises more than we do (quote style, redundant parentheses,
  ``1_000`` vs ``1000``), so we err on the side of reporting a change.
* ``missed``: the oracle says changed and we do not. This would be a bug: a real
  change that test selection would never see.

Usage:
    python benchmarks/changed_symbols/oracle.py --repo PATH [--commits 300]
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import statistics
import subprocess
import sys
import time
import warnings
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from analysis.diff import parse_unified_diff
from analysis.model import MODULE_NAME, ChangeKind, FileStatus
from analysis.sources import GitSnapshot, git_diff
from analysis.symbols import detect_changed_symbols

_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_REAL = {ChangeKind.ADDED, ChangeKind.DELETED, ChangeKind.MODIFIED}


@dataclass
class OracleSymbol:
    key: str
    is_function: bool
    parent: str | None
    dump: str


def oracle_symbols(source: bytes) -> dict[str, OracleSymbol] | None:
    """Symbols of one file according to CPython, or None if it does not parse."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None

    symbols: dict[str, OracleSymbol] = {}
    seen: Counter[str] = Counter()

    def dump(node: ast.AST, *, keep_marker: bool) -> str:
        return ast.dump(_without_nested(node, keep_marker=keep_marker))

    def visit(statements: list[ast.stmt], parent: str | None, qualifier: str) -> None:
        for definition in _definitions_in(statements):
            qualified = f"{qualifier}{definition.name}"
            seen[qualified] += 1
            key = qualified if seen[qualified] == 1 else f"{qualified}#{seen[qualified]}"
            is_function = isinstance(definition, _FUNCTIONS)
            symbols[key] = OracleSymbol(
                key, is_function, parent, dump(definition, keep_marker=is_function)
            )
            inner = f"{qualified}.<locals>." if is_function else f"{qualified}."
            visit(definition.body, key, inner)

    symbols[MODULE_NAME] = OracleSymbol(MODULE_NAME, False, None, dump(tree, keep_marker=False))
    visit(tree.body, MODULE_NAME, "")
    return symbols


def _definitions_in(
    statements: list[ast.stmt],
) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    """Definitions among these statements, looking inside if/for/try/with/match."""
    found: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []
    for statement in statements:
        if isinstance(statement, _DEFINITIONS):
            found.append(statement)
            continue
        for name, value in ast.iter_fields(statement):
            if name in ("body", "orelse", "finalbody") and isinstance(value, list):
                found.extend(_definitions_in(value))
            elif name in ("handlers", "cases") and isinstance(value, list):
                for clause in value:
                    found.extend(_definitions_in(clause.body))
    return found


def _without_nested(node: ast.AST, *, keep_marker: bool) -> ast.AST:
    """Copy of ``node`` with nested definitions cut out, as our fingerprints do."""

    class Cut(ast.NodeTransformer):
        def cut(self, _definition: ast.AST) -> ast.AST | None:
            return ast.Expr(ast.Constant("<nested-definition>")) if keep_marker else None

        visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = cut

    clone = copy.deepcopy(node)
    for name, value in ast.iter_fields(clone):
        if isinstance(value, list):
            setattr(
                clone,
                name,
                [Cut().visit(item) if isinstance(item, ast.AST) else item for item in value],
            )
            setattr(clone, name, [item for item in getattr(clone, name) if item is not None])
        elif isinstance(value, ast.AST):
            setattr(clone, name, Cut().visit(value))
    return clone


def oracle_changes(
    base: dict[str, OracleSymbol], head: dict[str, OracleSymbol]
) -> dict[str, ChangeKind]:
    changes: dict[str, ChangeKind] = {}
    for key, symbol in head.items():
        if key not in base:
            changes[key] = ChangeKind.ADDED
        elif base[key].dump != symbol.dump:
            changes[key] = ChangeKind.MODIFIED
    for key in base:
        if key not in head:
            changes[key] = ChangeKind.DELETED

    # Same rule as ours: a change inside a function reaches its enclosing functions.
    for key in list(changes):
        side = head if key in head else base
        parent = side[key].parent
        while parent is not None:
            if parent in base and parent in head and head[parent].is_function:
                changes.setdefault(parent, ChangeKind.MODIFIED)
            parent = side[parent].parent
    return changes


@dataclass
class Tally:
    commits: int = 0
    files: int = 0
    files_not_valid_python: int = 0
    symbols_compared: int = 0
    agree_changed: int = 0
    agree_unchanged: int = 0
    extra: int = 0
    missed: int = 0
    kind_mismatch: int = 0
    cosmetic: int = 0
    seconds: list[float] = field(default_factory=list)
    examples: dict[str, list[str]] = field(
        default_factory=lambda: {"extra": [], "missed": [], "kind_mismatch": []}
    )

    def note(self, group: str, text: str) -> None:
        if len(self.examples[group]) < 15:
            self.examples[group].append(text)


def compare_commit(repo: Path, commit: str, tally: Tally) -> None:
    base = GitSnapshot(repo, f"{commit}^")
    head = GitSnapshot(repo, commit)

    started = time.perf_counter()
    diffs = parse_unified_diff(git_diff(repo, base.commit, head.commit))
    change_set = detect_changed_symbols(diffs, base, head)
    tally.seconds.append(time.perf_counter() - started)
    tally.commits += 1

    for diff, change in zip(diffs, change_set.files, strict=True):
        if change.language != "python" or change.skipped is not None:
            continue
        if change.status not in (FileStatus.MODIFIED, FileStatus.RENAMED):
            continue  # whole-file adds and deletes have nothing to disagree about
        assert diff.old_path is not None and diff.new_path is not None
        oracle_base = oracle_symbols(base.read(diff.old_path) or b"")
        oracle_head = oracle_symbols(head.read(diff.new_path) or b"")
        if oracle_base is None or oracle_head is None:
            tally.files_not_valid_python += 1
            continue
        tally.files += 1

        expected = oracle_changes(oracle_base, oracle_head)
        ours = {symbol.key: symbol.change for symbol in change.symbols}
        tally.cosmetic += sum(1 for kind in ours.values() if kind is ChangeKind.COSMETIC)
        actual = {key: kind for key, kind in ours.items() if kind in _REAL}

        for key in sorted(set(oracle_base) | set(oracle_head)):
            tally.symbols_compared += 1
            want, got = expected.get(key), actual.get(key)
            where = f"{commit[:10]} {change.path}::{key}"
            if want == got:
                if want is None:
                    tally.agree_unchanged += 1
                else:
                    tally.agree_changed += 1
            elif want is None:
                tally.extra += 1
                tally.note("extra", f"{where} (ours: {got})")
            elif got is None:
                tally.missed += 1
                tally.note("missed", f"{where} (oracle: {want})")
            else:
                tally.kind_mismatch += 1
                tally.note("kind_mismatch", f"{where} (ours: {got}, oracle: {want})")

        unknown = set(actual) - set(oracle_base) - set(oracle_head)
        for key in sorted(unknown):
            tally.kind_mismatch += 1
            tally.note(
                "kind_mismatch", f"{commit[:10]} {change.path}::{key} (only we see this symbol)"
            )


def recent_commits(repo: Path, limit: int) -> list[str]:
    """Latest non-merge commits that touch Python files and have a parent."""
    listed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "log",
            "--no-merges",
            "--format=%H %P",
            f"-n{limit * 2}",
            "--",
            "*.py",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    commits: list[str] = []
    for line in listed:
        commit, *parents = line.split()
        has_parent = (
            len(parents) == 1
            and subprocess.run(
                ["git", "-C", str(repo), "cat-file", "-e", f"{parents[0]}^{{commit}}"],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        if has_parent:
            commits.append(commit)
        if len(commits) == limit:
            break
    return commits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--commits", type=int, default=300)
    parser.add_argument("--json", type=Path, help="also write the numbers to this file")
    arguments = parser.parse_args()

    tally = Tally()
    for commit in recent_commits(arguments.repo, arguments.commits):
        compare_commit(arguments.repo, commit, tally)

    changed_by_oracle = tally.agree_changed + tally.missed + tally.kind_mismatch
    summary = {
        "python": sys.version.split()[0],
        "commits": tally.commits,
        "files_compared": tally.files,
        "files_skipped_not_valid_for_this_python": tally.files_not_valid_python,
        "symbols_compared": tally.symbols_compared,
        "agree_changed": tally.agree_changed,
        "agree_unchanged": tally.agree_unchanged,
        "extra_reported_by_us": tally.extra,
        "missed_by_us": tally.missed,
        "kind_mismatch": tally.kind_mismatch,
        "cosmetic_only_symbols": tally.cosmetic,
        "recall_of_oracle_changes": (
            round(tally.agree_changed / changed_by_oracle, 4) if changed_by_oracle else None
        ),
        "median_seconds_per_commit": round(statistics.median(tally.seconds), 4)
        if tally.seconds
        else None,
        "max_seconds_per_commit": round(max(tally.seconds), 4) if tally.seconds else None,
    }
    print(json.dumps(summary, indent=2))
    for group, examples in tally.examples.items():
        if examples:
            print(f"\n{group} (first {len(examples)}):")
            for example in examples:
                print(f"  {example}")
    if arguments.json:
        arguments.json.write_text(
            json.dumps({**summary, "examples": tally.examples}, indent=2) + "\n"
        )
    return 1 if tally.missed or tally.kind_mismatch else 0


if __name__ == "__main__":
    sys.exit(main())
