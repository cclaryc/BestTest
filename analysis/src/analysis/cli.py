"""Command-line entry point.

Two ways to say which change to analyse:

* ``--repo`` with ``--base`` and ``--head``: read both versions from a local git
  repository and let git compute the diff.
* ``--diff`` with ``--base-dir`` and ``--head-dir``: read a diff file and two
  directories. Needs no git, which makes it handy for examples and tests.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from analysis.diff import DiffParseError, parse_unified_diff
from analysis.model import ChangedSymbol, ChangeKind, ChangeSet, SymbolKind
from analysis.sources import (
    DirectorySnapshot,
    GitError,
    GitSnapshot,
    Snapshot,
    git_diff,
    merge_base,
)
from analysis.symbols import detect_changed_symbols

_MARKS = {
    ChangeKind.ADDED: "A",
    ChangeKind.DELETED: "D",
    ChangeKind.MODIFIED: "M",
    ChangeKind.COSMETIC: "c",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        diff_text, base, head = _inputs(arguments, parser)
        change_set = detect_changed_symbols(parse_unified_diff(diff_text), base, head)
    except (GitError, DiffParseError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    _write(_render_json(change_set) if arguments.format == "json" else _render_text(change_set))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="besttest-analysis",
        description="Static analysis for BestTest.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    changed = commands.add_parser(
        "changed-symbols",
        help="list the functions, methods and classes a change touches",
        description="List the functions, methods and classes a change touches.",
    )

    from_git = changed.add_argument_group("from a git repository")
    from_git.add_argument("--repo", type=Path, help="path to a local git repository")
    from_git.add_argument("--base", help="revision the change is measured against, e.g. main")
    from_git.add_argument("--head", default="HEAD", help="revision with the change (default: HEAD)")
    from_git.add_argument(
        "--no-merge-base",
        action="store_true",
        help="compare base and head directly instead of from their common ancestor",
    )

    from_files = changed.add_argument_group("from a diff file and two directories")
    from_files.add_argument("--diff", type=Path, help="unified diff file")
    from_files.add_argument("--base-dir", type=Path, help="directory holding the base version")
    from_files.add_argument("--head-dir", type=Path, help="directory holding the head version")

    changed.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def _inputs(
    arguments: argparse.Namespace, parser: argparse.ArgumentParser
) -> tuple[str, Snapshot, Snapshot]:
    file_mode = (arguments.diff, arguments.base_dir, arguments.head_dir)
    if any(value is not None for value in file_mode):
        if not all(value is not None for value in file_mode):
            parser.error("--diff, --base-dir and --head-dir must be given together")
        if arguments.repo is not None or arguments.base is not None:
            parser.error("use either --repo/--base/--head or --diff/--base-dir/--head-dir")
        text = arguments.diff.read_text(encoding="utf-8", errors="replace")
        return text, DirectorySnapshot(arguments.base_dir), DirectorySnapshot(arguments.head_dir)

    if arguments.base is None:
        parser.error("--base is required (or use --diff with --base-dir and --head-dir)")
    repo = arguments.repo if arguments.repo is not None else Path(".")
    # A pull request shows what the branch added since it split from the target
    # branch, not everything that differs from the target's latest commit.
    base = (
        arguments.base
        if arguments.no_merge_base
        else merge_base(repo, arguments.base, arguments.head)
    )
    base_snapshot = GitSnapshot(repo, base)
    head_snapshot = GitSnapshot(repo, arguments.head)
    diff_text = git_diff(repo, base_snapshot.commit, head_snapshot.commit)
    return diff_text, base_snapshot, head_snapshot


def _render_json(change_set: ChangeSet) -> str:
    return json.dumps(change_set.to_dict(), indent=2, ensure_ascii=False)


def _render_text(change_set: ChangeSet) -> str:
    if not change_set.files:
        return "No changes."
    lines: list[str] = []
    for change in change_set:
        title = f"{change.path} ({change.status.value}"
        if change.old_path:
            title += f" from {change.old_path}"
        lines.append(title + ")")
        if change.skipped is not None:
            lines.append(f"  skipped: {change.skipped.value.replace('_', ' ')}")
        elif not change.symbols:
            lines.append("  no symbols changed")
        if change.syntax_errors:
            lines.append("  note: syntax errors found, results are best effort")

        width = max((len(symbol.key) for symbol in change.symbols), default=0)
        for symbol in change.symbols:
            lines.append(
                f"  {_MARKS[symbol.change]}  {symbol.kind.value:<8}  "
                f"{symbol.key:<{width}}  {_details(symbol)}".rstrip()
            )
        lines.append("")
    lines.append("A added  D deleted  M modified  c cosmetic (comments or layout only)")
    return "\n".join(lines)


def _details(symbol: ChangedSymbol) -> str:
    located = symbol.head if symbol.head is not None else symbol.base
    assert located is not None
    span = located.span
    if symbol.kind is SymbolKind.MODULE:
        where = "top-level code"
    elif span.start_line == span.end_line:
        where = f"line {span.start_line}"
    else:
        where = f"lines {span.start_line}-{span.end_line}"
    if symbol.change is ChangeKind.DELETED:
        where += " in base"
    if symbol.parts:
        where += f"  [{', '.join(part.value for part in symbol.parts)}]"
    return where


def _write(text: str) -> None:
    # A Windows console may use a legacy code page that cannot print every path.
    # Replace what it cannot show instead of crashing.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="backslashreplace")
    print(text)


if __name__ == "__main__":
    sys.exit(main())
