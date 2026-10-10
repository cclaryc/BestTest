from __future__ import annotations

from dataclasses import dataclass

from analysis.model import FileStatus


@dataclass(frozen=True, slots=True)
class FileDiff:
    """What a unified diff says about one file, reduced to what analysis needs.

    A diff has two sides with independent line numbering. Removed lines only
    exist in the base file, added lines only in the head file, so each set is
    numbered against its own side.
    """

    status: FileStatus
    old_path: str | None
    new_path: str | None
    removed_lines: frozenset[int] = frozenset()
    added_lines: frozenset[int] = frozenset()
    is_binary: bool = False

    def __post_init__(self) -> None:
        if self.old_path is None and self.new_path is None:
            raise ValueError("a file diff needs at least one path")

    @property
    def path(self) -> str:
        """The path to report: where the file lives now, or lived if deleted."""
        path = self.new_path if self.new_path is not None else self.old_path
        assert path is not None
        return path
