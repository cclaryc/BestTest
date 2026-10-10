"""Turn unified diff text into :class:`FileDiff` records.

The text format itself is parsed by the ``unidiff`` library. This module is the
only place that imports it, so the rest of the code depends on our own small
model and the library can be replaced without touching anything else.
"""

from __future__ import annotations

import re

from unidiff.errors import UnidiffParseError
from unidiff.patch import PatchSet

from analysis.diff.model import FileDiff
from analysis.model import FileStatus

_DEV_NULL = "/dev/null"
_ESCAPE = re.compile(rb"\\([0-7]{1,3}|.)", re.DOTALL)
_NAMED_ESCAPES = {
    b"t": b"\t",
    b"n": b"\n",
    b"r": b"\r",
    b"a": b"\a",
    b"b": b"\b",
    b"f": b"\f",
    b"v": b"\v",
}


class DiffParseError(ValueError):
    """The input is not a well-formed unified diff."""


def parse_unified_diff(text: str) -> list[FileDiff]:
    """Parse the output of ``git diff`` (or GitHub's ``.diff`` endpoint)."""
    try:
        patch_set = PatchSet(text)
    except UnidiffParseError as error:
        raise DiffParseError(str(error)) from error

    diffs: list[FileDiff] = []
    for patched in patch_set:
        old_path = None if patched.is_added_file else _clean_path(patched.source_file, "a/")
        new_path = None if patched.is_removed_file else _clean_path(patched.target_file, "b/")
        if old_path is None and new_path is None:
            raise DiffParseError("file entry has neither a source nor a target path")

        removed: set[int] = set()
        added: set[int] = set()
        for hunk in patched:
            for line in hunk:
                if line.is_removed and line.source_line_no is not None:
                    removed.add(line.source_line_no)
                elif line.is_added and line.target_line_no is not None:
                    added.add(line.target_line_no)

        diffs.append(
            FileDiff(
                status=_status(old_path, new_path),
                old_path=old_path,
                new_path=new_path,
                removed_lines=frozenset(removed),
                added_lines=frozenset(added),
                is_binary=bool(patched.is_binary_file),
            )
        )
    return diffs


def _status(old_path: str | None, new_path: str | None) -> FileStatus:
    if old_path is None:
        return FileStatus.ADDED
    if new_path is None:
        return FileStatus.DELETED
    if old_path != new_path:
        return FileStatus.RENAMED
    return FileStatus.MODIFIED


def _clean_path(raw: str | None, prefix: str) -> str | None:
    """Normalise a path as it appears in a diff header.

    Git prefixes paths with ``a/`` and ``b/``, and wraps a path in double quotes
    with C-style escapes when it contains unusual bytes (non-ASCII characters
    appear as octal, for example ``"b/caf\\303\\251.py"``).
    """
    if raw is None:
        return None
    path = raw.strip()
    if path.startswith('"') and path.endswith('"') and len(path) >= 2:
        path = _unquote(path[1:-1])
    if path == _DEV_NULL:
        return None
    if path.startswith(prefix):
        path = path[len(prefix) :]
    return path


def _unquote(quoted: str) -> str:
    def decode(match: re.Match[bytes]) -> bytes:
        escape = match.group(1)
        if escape[:1].isdigit():
            return bytes([int(escape, 8) & 0xFF])
        # Anything else (a quote, a backslash) stands for itself.
        return _NAMED_ESCAPES.get(escape, escape)

    return _ESCAPE.sub(decode, quoted.encode("utf-8")).decode("utf-8", errors="replace")
