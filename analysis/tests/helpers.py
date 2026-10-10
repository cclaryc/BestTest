"""Shared test helpers.

Most tests describe a change as two strings of source code. ``analyse`` builds
the diff between them with ``difflib``, so the tests need neither git nor files.
"""

from __future__ import annotations

import difflib
from textwrap import dedent

from analysis.diff import parse_unified_diff
from analysis.model import ChangedSymbol, ExtractedSymbol, FileChange
from analysis.parsing import PythonAdapter
from analysis.sources import MappingSnapshot
from analysis.symbols import detect_changed_symbols

PATH = "pkg/module.py"


def clean(source: str) -> str:
    return dedent(source).lstrip("\n")


def unified_diff(
    base: str | None, head: str | None, *, path: str = PATH, old_path: str | None = None
) -> str:
    """Build a git-style diff for one file. None means the file does not exist."""
    old_path = old_path or path
    old_lines = [] if base is None else base.splitlines(keepends=True)
    new_lines = [] if head is None else head.splitlines(keepends=True)
    body = "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="/dev/null" if base is None else f"a/{old_path}",
            tofile="/dev/null" if head is None else f"b/{path}",
            n=0,
        )
    )
    header = f"diff --git a/{old_path} b/{path}\n"
    if base is None:
        header += "new file mode 100644\n"
    elif head is None:
        header += "deleted file mode 100644\n"
    elif old_path != path:
        header += f"rename from {old_path}\nrename to {path}\n"
    return header + body


def analyse_file(
    base: str | None, head: str | None, *, path: str = PATH, old_path: str | None = None
) -> FileChange:
    base = None if base is None else clean(base)
    head = None if head is None else clean(head)
    diff = unified_diff(base, head, path=path, old_path=old_path)
    change_set = detect_changed_symbols(
        parse_unified_diff(diff),
        MappingSnapshot({} if base is None else {old_path or path: base}),
        MappingSnapshot({} if head is None else {path: head}),
    )
    assert len(change_set.files) == 1
    return change_set.files[0]


def analyse(base: str | None, head: str | None) -> dict[str, ChangedSymbol]:
    """Changed symbols of a single-file change, by key."""
    return {symbol.key: symbol for symbol in analyse_file(base, head).symbols}


def extract(source: str) -> dict[str, ExtractedSymbol]:
    adapter = PythonAdapter()
    symbols = adapter.symbols(adapter.parse(clean(source).encode()), PATH)
    return {extracted.symbol.key: extracted for extracted in symbols}
