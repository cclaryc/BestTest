"""Finding a repository snapshot from the id in a request.

The backend downloads a repository at a given commit, unpacks it into a
directory on a shared volume, and sends the directory's *name*. The service
resolves that name here. Source code therefore never travels in a request body,
and the service needs no GitHub credentials at all.
"""

from __future__ import annotations

import re
from pathlib import Path

from analysis.api.contracts import SNAPSHOT_ID_PATTERN
from analysis.sources import DirectorySnapshot

_SNAPSHOT_ID = re.compile(SNAPSHOT_ID_PATTERN)


class SnapshotNotFound(LookupError):
    def __init__(self, snapshot_id: str) -> None:
        super().__init__(snapshot_id)
        self.snapshot_id = snapshot_id


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def is_ready(self) -> bool:
        return self._root.is_dir()

    def open(self, snapshot_id: str) -> DirectorySnapshot:
        # The request model already enforces this pattern. It is checked again
        # because this is the line that touches the file system, and it should
        # stay safe even if someone calls it from a new code path.
        if not _SNAPSHOT_ID.fullmatch(snapshot_id):
            raise SnapshotNotFound(snapshot_id)

        root = self._root.resolve()
        candidate = (root / snapshot_id).resolve()
        # After following symlinks, the snapshot must still be a directory
        # directly inside the root.
        if candidate.parent != root or not candidate.is_dir():
            raise SnapshotNotFound(snapshot_id)
        return DirectorySnapshot(candidate)
