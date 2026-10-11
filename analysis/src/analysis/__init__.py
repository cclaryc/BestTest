"""Static analysis core of BestTest.

Milestone 1 exposes one capability: given a unified diff and the two versions of
the repository it connects, report which functions, methods and classes changed.
"""

from analysis.model import (
    ChangedSymbol,
    ChangeKind,
    ChangeSet,
    FileChange,
    FileStatus,
    Part,
    SkipReason,
    Span,
    Symbol,
    SymbolKind,
)
from analysis.symbols.changed import Limits, detect_changed_symbols

__all__ = [
    "ChangeKind",
    "ChangeSet",
    "ChangedSymbol",
    "FileChange",
    "FileStatus",
    "Limits",
    "Part",
    "SkipReason",
    "Span",
    "Symbol",
    "SymbolKind",
    "detect_changed_symbols",
]

__version__ = "0.2.0"
