import os

import pytest

from analysis.sources import DirectorySnapshot, MappingSnapshot, _is_safe_relative_path


def test_mapping_snapshot_accepts_text_and_bytes():
    snapshot = MappingSnapshot({"a.py": "x = 1\n", "b.py": b"y = 2\n"})

    assert snapshot.read("a.py") == b"x = 1\n"
    assert snapshot.read("b.py") == b"y = 2\n"
    assert snapshot.read("missing.py") is None


def test_directory_snapshot_reads_files_by_relative_path(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_bytes(b"x = 1\n")

    snapshot = DirectorySnapshot(tmp_path)

    assert snapshot.read("pkg/mod.py") == b"x = 1\n"
    assert snapshot.read("pkg/missing.py") is None
    assert snapshot.read("pkg") is None


@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        "pkg/../../secret.txt",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "pkg\\..\\..\\secret.txt",
        "",
        "pkg/\x00.py",
    ],
)
def test_directory_snapshot_refuses_paths_that_leave_the_root(tmp_path, path):
    # Paths come from a diff, and a diff can be written by anyone.
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("secret")

    assert DirectorySnapshot(root).read(path) is None


def test_directory_snapshot_refuses_symlinks_that_leave_the_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    try:
        os.symlink(tmp_path / "secret.txt", root / "link.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")

    assert DirectorySnapshot(root).read("link.py") is None


@pytest.mark.parametrize("path", ["pkg/mod.py", "mod.py", "a/b/c/d.py", "pkg/..hidden.py"])
def test_ordinary_relative_paths_are_safe(path):
    assert _is_safe_relative_path(path)


@pytest.mark.parametrize(
    "path",
    ["../x.py", "a/../../x.py", "a/..", "/abs/x.py", "C:/x.py", "a\\b.py", "", "a/\x00.py"],
)
def test_escaping_paths_are_rejected_before_touching_the_disk(path):
    # DirectorySnapshot also checks the resolved path. This first check is what
    # protects snapshots that never resolve a path, such as GitSnapshot.
    assert not _is_safe_relative_path(path)
