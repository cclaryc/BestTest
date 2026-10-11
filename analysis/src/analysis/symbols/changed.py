"""Map a diff to the symbols it changes.

The diff says *where* text changed. The syntax trees of the two versions say
*what* changed. Both are needed:

* Lines alone cannot tell a rewritten condition from a reworded comment, and
  they report a function that was merely moved as changed.
* Trees alone would mean parsing and comparing every file in the repository.

So the diff picks the files and supplies the touched lines, and each symbol is
then classified by comparing its fingerprint in base and head.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace

from analysis.diff.model import FileDiff
from analysis.model import (
    ChangedSymbol,
    ChangeKind,
    ChangeSet,
    ExtractedSymbol,
    FileChange,
    FileStatus,
    Part,
    SkipReason,
    SymbolKind,
)
from analysis.parsing import AdapterRegistry, LanguageAdapter, default_registry
from analysis.sources import Snapshot

_REAL_CHANGES = frozenset({ChangeKind.ADDED, ChangeKind.DELETED, ChangeKind.MODIFIED})
_FUNCTION_KINDS = frozenset({SymbolKind.FUNCTION, SymbolKind.METHOD})
_PART_ORDER = (Part.DECORATORS, Part.SIGNATURE, Part.BODY, Part.NESTED)


@dataclass(frozen=True, slots=True)
class Limits:
    """Upper bounds on the work one call may do.

    The input is a diff of someone else's code, so its size is not ours to
    choose. Each limit turns "this request takes forever" into "these files were
    skipped, and the result says so".
    """

    max_file_bytes: int = 1_000_000
    max_files: int | None = None
    """How many files to parse. Files that are skipped anyway do not count."""
    time_budget_seconds: float | None = None
    """Checked between files, so one call can overrun by one file's parse time."""


def detect_changed_symbols(
    diffs: Iterable[FileDiff],
    base: Snapshot,
    head: Snapshot,
    *,
    adapters: AdapterRegistry | None = None,
    limits: Limits | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ChangeSet:
    """Report the symbols each file diff adds, deletes or modifies.

    ``base`` and ``head`` must be the two versions the diff was computed between.
    Files in a language without an adapter are listed but not analysed. Files
    left out because a limit was reached are listed with the reason, and the
    result's ``complete`` flag is then False.
    """
    registry = adapters if adapters is not None else default_registry()
    limits = limits if limits is not None else Limits()
    started = clock()
    analysed = 0
    changes: list[FileChange] = []

    for diff in diffs:
        limit_hit: SkipReason | None = None
        if limits.max_files is not None and analysed >= limits.max_files:
            limit_hit = SkipReason.TOO_MANY_FILES
        elif (
            limits.time_budget_seconds is not None
            and clock() - started > limits.time_budget_seconds
        ):
            limit_hit = SkipReason.TIME_BUDGET_EXCEEDED

        change = _analyse_file(diff, base, head, registry, limits.max_file_bytes, limit_hit)
        if change.skipped is None:
            analysed += 1
        changes.append(change)

    return ChangeSet(tuple(changes))


def _analyse_file(
    diff: FileDiff,
    base: Snapshot,
    head: Snapshot,
    registry: AdapterRegistry,
    max_file_bytes: int,
    limit_hit: SkipReason | None,
) -> FileChange:
    change = FileChange(
        path=diff.path,
        status=diff.status,
        old_path=diff.old_path if diff.status is FileStatus.RENAMED else None,
    )
    if diff.is_binary:
        return replace(change, skipped=SkipReason.BINARY)
    adapter = registry.for_path(diff.path)
    if adapter is None:
        return replace(change, skipped=SkipReason.UNSUPPORTED_LANGUAGE)
    change = replace(change, language=adapter.name)
    if limit_hit is not None:
        return replace(change, skipped=limit_hit)

    base_source = base.read(diff.old_path) if diff.old_path is not None else None
    head_source = head.read(diff.new_path) if diff.new_path is not None else None
    if (diff.old_path is not None and base_source is None) or (
        diff.new_path is not None and head_source is None
    ):
        return replace(change, skipped=SkipReason.MISSING_SOURCE)
    if max(len(base_source or b""), len(head_source or b"")) > max_file_bytes:
        return replace(change, skipped=SkipReason.TOO_LARGE)

    base_symbols, base_errors = _extract(adapter, base_source, diff.old_path)
    head_symbols, head_errors = _extract(adapter, head_source, diff.new_path)
    return replace(
        change,
        symbols=classify(base_symbols, head_symbols, diff),
        syntax_errors=base_errors or head_errors,
    )


def _extract(
    adapter: LanguageAdapter, source: bytes | None, path: str | None
) -> tuple[list[ExtractedSymbol], bool]:
    if source is None or path is None:
        return [], False
    parsed = adapter.parse(source)
    return adapter.symbols(parsed, path), parsed.has_errors


def classify(
    base_symbols: list[ExtractedSymbol],
    head_symbols: list[ExtractedSymbol],
    diff: FileDiff,
) -> tuple[ChangedSymbol, ...]:
    """Compare two versions of one file, symbol by symbol.

    Symbols are paired by key (qualified name plus ordinal). A symbol with no
    partner was added or deleted. A pair whose fingerprints differ was modified.
    A pair with equal fingerprints but touched lines changed only cosmetically.
    Everything else is unchanged and left out.
    """
    base_by_key = {extracted.symbol.key: extracted for extracted in base_symbols}
    head_by_key = {extracted.symbol.key: extracted for extracted in head_symbols}
    changes: dict[str, ChangedSymbol] = {}

    for key, in_head in head_by_key.items():
        in_base = base_by_key.get(key)
        touched_head = tuple(sorted(in_head.owned_lines & diff.added_lines))
        if in_base is None:
            changes[key] = ChangedSymbol(
                ChangeKind.ADDED, None, in_head.symbol, touched_head_lines=touched_head
            )
            continue

        touched_base = tuple(sorted(in_base.owned_lines & diff.removed_lines))
        parts = tuple(
            part
            for part in _PART_ORDER
            if in_base.fingerprints.get(part) != in_head.fingerprints.get(part)
        )
        if parts:
            kind = ChangeKind.MODIFIED
        elif touched_base or touched_head:
            kind = ChangeKind.COSMETIC
        else:
            continue
        changes[key] = ChangedSymbol(
            kind, in_base.symbol, in_head.symbol, parts, touched_base, touched_head
        )

    for key, in_base in base_by_key.items():
        if key not in head_by_key:
            changes[key] = ChangedSymbol(
                ChangeKind.DELETED,
                in_base.symbol,
                None,
                touched_base_lines=tuple(sorted(in_base.owned_lines & diff.removed_lines)),
            )

    _propagate_to_enclosing_functions(changes, base_by_key, head_by_key)
    return tuple(sorted(changes.values(), key=_position))


def _propagate_to_enclosing_functions(
    changes: dict[str, ChangedSymbol],
    base_by_key: Mapping[str, ExtractedSymbol],
    head_by_key: Mapping[str, ExtractedSymbol],
) -> None:
    """Mark a function as modified when a definition nested inside it changed.

    A nested function or local class cannot be called from outside: callers
    reach it only through the function that contains it. Reporting just the
    inner definition would hide the change from anything that looks for callers
    of the outer one, so the outer function is reported too, with ``Part.NESTED``.

    Classes are not marked this way. A changed method is reachable by its own
    name, and marking the class would make every user of the class look affected.
    """
    for key, change in list(changes.items()):
        if change.change not in _REAL_CHANGES:
            continue
        parents = head_by_key if key in head_by_key else base_by_key
        parent_key = parents[key].parent_key
        while parent_key is not None:
            in_base = base_by_key.get(parent_key)
            in_head = head_by_key.get(parent_key)
            # An ancestor missing from one side is itself added or deleted, and
            # already reported as such.
            if (
                in_base is not None
                and in_head is not None
                and in_head.symbol.kind in _FUNCTION_KINDS
            ):
                changes[parent_key] = _with_nested_change(changes.get(parent_key), in_base, in_head)
            parent_key = parents[parent_key].parent_key


def _with_nested_change(
    existing: ChangedSymbol | None, in_base: ExtractedSymbol, in_head: ExtractedSymbol
) -> ChangedSymbol:
    if existing is None:
        return ChangedSymbol(ChangeKind.MODIFIED, in_base.symbol, in_head.symbol, (Part.NESTED,))
    parts = existing.parts if Part.NESTED in existing.parts else (*existing.parts, Part.NESTED)
    return ChangedSymbol(
        ChangeKind.MODIFIED,
        existing.base,
        existing.head,
        parts,
        existing.touched_base_lines,
        existing.touched_head_lines,
    )


def _position(change: ChangedSymbol) -> tuple[int, int, str]:
    """Sort by where the symbol sits in head, or sat in base if it was deleted."""
    if change.head is not None:
        return (change.head.span.start_line, 0, change.key)
    assert change.base is not None
    return (change.base.span.start_line, 1, change.key)
