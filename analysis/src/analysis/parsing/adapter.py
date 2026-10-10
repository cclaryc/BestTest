"""The seam between language-specific parsing and language-neutral algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from tree_sitter import Tree

from analysis.model import ExtractedSymbol


@dataclass(frozen=True, slots=True)
class ParsedSource:
    source: bytes
    tree: Tree

    @property
    def has_errors(self) -> bool:
        """Tree-sitter always returns a tree; this says whether it had to guess."""
        return bool(self.tree.root_node.has_error)


class LanguageAdapter(Protocol):
    """Everything the analysis needs to know about one programming language.

    Later milestones add ``imports``, ``calls`` and ``is_test`` here. Parsing is a
    separate step so that one parse can feed all of them.
    """

    name: str
    extensions: tuple[str, ...]

    def parse(self, source: bytes) -> ParsedSource: ...

    def symbols(self, parsed: ParsedSource, path: str) -> list[ExtractedSymbol]: ...


class AdapterRegistry:
    """Chooses an adapter from a file's extension."""

    def __init__(self, adapters: tuple[LanguageAdapter, ...]) -> None:
        self._by_extension: dict[str, LanguageAdapter] = {}
        for adapter in adapters:
            for extension in adapter.extensions:
                self._by_extension[extension.lower()] = adapter

    def for_path(self, path: str) -> LanguageAdapter | None:
        return self._by_extension.get(PurePosixPath(path).suffix.lower())
