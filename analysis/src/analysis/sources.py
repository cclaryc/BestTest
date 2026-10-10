"""Where file contents come from.

Change detection needs both versions of every changed file. A :class:`Snapshot`
is one version of a repository that can be asked for a file by path. Paths come
from a diff, which is untrusted input, so every implementation here refuses to
read outside the repository it was given.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Protocol


class Snapshot(Protocol):
    def read(self, path: str) -> bytes | None:
        """Return the file's bytes, or None when this version has no such file."""
        ...


class MappingSnapshot:
    """An in-memory snapshot, mainly for tests."""

    def __init__(self, files: Mapping[str, bytes | str]) -> None:
        self._files = {
            path: content.encode("utf-8") if isinstance(content, str) else content
            for path, content in files.items()
        }

    def read(self, path: str) -> bytes | None:
        return self._files.get(path)


class DirectorySnapshot:
    """A snapshot that is a directory on disk."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()

    def read(self, path: str) -> bytes | None:
        if not _is_safe_relative_path(path):
            return None
        candidate = (self._root / path).resolve()
        # resolve() follows symlinks, so a link pointing out of the snapshot is
        # caught by this check as well.
        if not candidate.is_relative_to(self._root) or not candidate.is_file():
            return None
        return candidate.read_bytes()


class GitError(RuntimeError):
    """A git command failed."""


class GitSnapshot:
    """One commit of a local git repository."""

    def __init__(self, repo: Path | str, commit: str) -> None:
        self._repo = Path(repo)
        self._commit = resolve_commit(self._repo, commit)

    @property
    def commit(self) -> str:
        return self._commit

    def read(self, path: str) -> bytes | None:
        if not _is_safe_relative_path(path):
            return None
        result = _git(self._repo, "cat-file", "blob", f"{self._commit}:{path}")
        return result.stdout if result.returncode == 0 else None


def resolve_commit(repo: Path | str, revision: str) -> str:
    """Turn a branch, tag or abbreviated hash into a full commit hash.

    Revisions are caller input. One that starts with ``-`` would be read by git
    as an option, so it is rejected before git ever sees it. Everything after
    this point uses the returned hash.
    """
    if not revision or revision.startswith("-"):
        raise GitError(f"not a valid revision: {revision!r}")
    result = _git(Path(repo), "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}")
    if result.returncode != 0:
        raise GitError(f"unknown revision: {revision!r}")
    return result.stdout.decode("ascii").strip()


def merge_base(repo: Path | str, first: str, second: str) -> str:
    """The commit where two histories diverged."""
    repo = Path(repo)
    result = _git(repo, "merge-base", resolve_commit(repo, first), resolve_commit(repo, second))
    if result.returncode != 0:
        raise GitError(f"no common ancestor between {first!r} and {second!r}")
    return result.stdout.decode("ascii").strip()


def git_diff(repo: Path | str, base: str, head: str) -> str:
    """Unified diff between two commits, with renames detected."""
    repo = Path(repo)
    result = _git(
        repo,
        # Print paths as UTF-8 instead of octal escapes.
        "-c",
        "core.quotepath=false",
        "diff",
        "--no-color",
        # A repository's git config can name external programs to produce diffs
        # or convert files. Never run them: analysis only reads.
        "--no-ext-diff",
        "--no-textconv",
        "--find-renames",
        # Context lines are not needed: only added and removed lines are used.
        "--unified=0",
        resolve_commit(repo, base),
        resolve_commit(repo, head),
        "--",
    )
    if result.returncode != 0:
        raise GitError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout.decode("utf-8", errors="replace")


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *arguments],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise GitError("git is not installed or not on PATH") from error


def _is_safe_relative_path(path: str) -> bool:
    if not path or "\x00" in path or "\\" in path:
        return False
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    # "C:/..." is absolute on Windows even though it has no leading slash.
    return ":" not in pure.parts[0]
