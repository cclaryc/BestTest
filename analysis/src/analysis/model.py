"""Records shared by every analysis stage.

These are plain, immutable data classes with no behaviour beyond naming and
serialisation. Parsing, diffing and change detection all speak in these terms, so
none of those packages has to import another one just to describe a symbol.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

MODULE_NAME = "<module>"
"""Qualified name of the pseudo-symbol that owns a file's top-level code."""


class SymbolKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"


class Part(StrEnum):
    """The piece of a definition that differs between base and head."""

    DECORATORS = "decorators"
    SIGNATURE = "signature"
    BODY = "body"
    NESTED = "nested"
    """A definition nested inside this function changed (see ``changed.py``)."""


class ChangeKind(StrEnum):
    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"
    COSMETIC = "cosmetic"
    """Lines were touched, but only comments, blank lines or layout differ."""


class FileStatus(StrEnum):
    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"
    RENAMED = "renamed"


class SkipReason(StrEnum):
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    BINARY = "binary"
    TOO_LARGE = "too_large"
    MISSING_SOURCE = "missing_source"


@dataclass(frozen=True, slots=True, order=True)
class Span:
    """A range of lines, 1-based and inclusive at both ends."""

    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, int]:
        return {"start_line": self.start_line, "end_line": self.end_line}


@dataclass(frozen=True, slots=True)
class Symbol:
    """A named definition in one version of one file."""

    path: str
    qualified_name: str
    kind: SymbolKind
    span: Span
    ordinal: int = 1
    """1 for the first definition of this name in the file, 2 for the next, and so on.

    Python allows the same qualified name to be defined more than once: a property
    and its setter, ``@overload`` stubs, or a function defined in both arms of an
    ``if``. The ordinal keeps those apart.
    """

    @property
    def key(self) -> str:
        """Identity of the symbol within its file, stable across base and head."""
        if self.ordinal == 1:
            return self.qualified_name
        return f"{self.qualified_name}#{self.ordinal}"

    @property
    def id(self) -> str:
        return f"{self.path}::{self.key}"


@dataclass(frozen=True, slots=True)
class ExtractedSymbol:
    """A symbol plus the facts change detection needs about it."""

    symbol: Symbol
    parent_key: str | None
    owned_lines: frozenset[int]
    """Non-blank lines in the symbol's span that are not part of a nested definition."""
    fingerprints: Mapping[Part, str]
    """One structural hash per part; comments and layout do not affect them."""


@dataclass(frozen=True, slots=True)
class ChangedSymbol:
    change: ChangeKind
    base: Symbol | None
    head: Symbol | None
    parts: tuple[Part, ...] = ()
    touched_base_lines: tuple[int, ...] = ()
    """Removed lines owned by the symbol, numbered as in the base file."""
    touched_head_lines: tuple[int, ...] = ()
    """Added lines owned by the symbol, numbered as in the head file."""

    def __post_init__(self) -> None:
        if self.base is None and self.head is None:
            raise ValueError("a changed symbol must exist in base or head")

    @property
    def _either(self) -> Symbol:
        symbol = self.head if self.head is not None else self.base
        assert symbol is not None
        return symbol

    @property
    def key(self) -> str:
        return self._either.key

    @property
    def qualified_name(self) -> str:
        return self._either.qualified_name

    @property
    def kind(self) -> SymbolKind:
        return self._either.kind

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "qualified_name": self.qualified_name,
            "kind": self.kind.value,
            "change": self.change.value,
            "parts": [part.value for part in self.parts],
            "base_span": self.base.span.to_dict() if self.base else None,
            "head_span": self.head.span.to_dict() if self.head else None,
            "touched_base_lines": list(self.touched_base_lines),
            "touched_head_lines": list(self.touched_head_lines),
        }


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    status: FileStatus
    old_path: str | None = None
    language: str | None = None
    symbols: tuple[ChangedSymbol, ...] = ()
    skipped: SkipReason | None = None
    syntax_errors: bool = False
    """True when either version did not parse cleanly; results are best effort."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "old_path": self.old_path,
            "status": self.status.value,
            "language": self.language,
            "skipped": self.skipped.value if self.skipped else None,
            "syntax_errors": self.syntax_errors,
            "symbols": [symbol.to_dict() for symbol in self.symbols],
        }


@dataclass(frozen=True, slots=True)
class ChangeSet:
    files: tuple[FileChange, ...] = field(default_factory=tuple)

    def __iter__(self) -> Iterator[FileChange]:
        return iter(self.files)

    def file(self, path: str) -> FileChange:
        for change in self.files:
            if change.path == path:
                return change
        raise KeyError(path)

    def to_dict(self) -> dict[str, Any]:
        return {"files": [change.to_dict() for change in self.files]}
