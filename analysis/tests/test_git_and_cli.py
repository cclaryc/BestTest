"""The CLI, the shipped example, and reading from a real git repository."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from analysis.cli import main
from analysis.sources import GitError, GitSnapshot, git_diff, merge_base, resolve_commit

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "discount"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def run_cli(capsys, *arguments: str) -> tuple[int, str, str]:
    code = main(list(arguments))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def example_arguments() -> list[str]:
    return [
        "changed-symbols",
        "--diff",
        str(EXAMPLE / "change.diff"),
        "--base-dir",
        str(EXAMPLE / "base"),
        "--head-dir",
        str(EXAMPLE / "head"),
    ]


# --- the shipped example --------------------------------------------------


def test_example_json_output(capsys):
    code, out, _ = run_cli(capsys, *example_arguments(), "--format", "json")

    (file_change,) = json.loads(out)["files"]
    assert code == 0
    assert file_change["path"] == "shop/pricing.py"
    assert {
        symbol["key"]: (symbol["change"], symbol["parts"]) for symbol in file_change["symbols"]
    } == {
        "<module>": ("modified", ["body"]),
        "clamp": ("cosmetic", []),
        "calculate_discount": ("modified", ["signature", "body"]),
        "Cart.clear": ("added", []),
    }


def test_example_text_output(capsys):
    code, out, _ = run_cli(capsys, *example_arguments())

    assert code == 0
    assert out.splitlines()[:5] == [
        "shop/pricing.py (modified)",
        "  M  module    <module>            top-level code  [body]",
        "  c  function  clamp               lines 6-8",
        "  M  function  calculate_discount  lines 11-14  [signature, body]",
        "  A  method    Cart.clear          lines 24-25",
    ]


def test_missing_diff_file_is_an_error_not_a_crash(capsys, tmp_path):
    code, _, err = run_cli(
        capsys,
        "changed-symbols",
        "--diff",
        str(tmp_path / "nope.diff"),
        "--base-dir",
        str(tmp_path),
        "--head-dir",
        str(tmp_path),
    )

    assert code == 2
    assert err.startswith("error:")


def test_file_mode_needs_all_three_options(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["changed-symbols", "--diff", "x.diff"])

    assert exit_info.value.code == 2


# --- a real repository ----------------------------------------------------


def git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments], check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with a main branch and a feature branch that have diverged.

        A --- C          main     (C edits other.py)
         \\
          B              feature  (B edits app.py)
    """
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--quiet", "--initial-branch=main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")

    (root / "app.py").write_text("def greet(name):\n    return 'hi ' + name\n")
    (root / "other.py").write_text("def other():\n    return 1\n")
    git(root, "add", "--all")
    git(root, "commit", "--quiet", "--message", "A")

    git(root, "switch", "--quiet", "--create", "feature")
    (root / "app.py").write_text("def greet(name):\n    return 'hello ' + name\n")
    git(root, "commit", "--quiet", "--all", "--message", "B")

    git(root, "switch", "--quiet", "main")
    (root / "other.py").write_text("def other():\n    return 2\n")
    git(root, "commit", "--quiet", "--all", "--message", "C")
    return root


@needs_git
def test_git_snapshot_reads_a_file_at_a_commit(repo):
    assert b"hello" in (GitSnapshot(repo, "feature").read("app.py") or b"")
    assert b"hello" not in (GitSnapshot(repo, "main").read("app.py") or b"")
    assert GitSnapshot(repo, "main").read("missing.py") is None
    assert GitSnapshot(repo, "main").read("../outside.py") is None


@needs_git
def test_revisions_that_look_like_options_are_rejected(repo):
    # Rejected by our own check, before git is started at all.
    with pytest.raises(GitError, match="not a valid revision"):
        resolve_commit(repo, "--output=/tmp/owned")
    with pytest.raises(GitError, match="unknown revision"):
        resolve_commit(repo, "no-such-branch")


@needs_git
def test_merge_base_is_where_the_branches_split(repo):
    assert merge_base(repo, "main", "feature") == git(repo, "rev-parse", "main~1")


@needs_git
def test_diff_from_the_merge_base_shows_only_the_branch_work(repo):
    direct = git_diff(repo, "main", "feature")
    from_split = git_diff(repo, merge_base(repo, "main", "feature"), "feature")

    # Compared directly, main's own later commit shows up as if the feature
    # branch had undone it.
    assert "other.py" in direct
    assert "other.py" not in from_split
    assert "app.py" in from_split


@needs_git
def test_cli_on_a_repository_uses_the_merge_base(capsys, repo):
    code, out, _ = run_cli(
        capsys,
        "changed-symbols",
        "--repo",
        str(repo),
        "--base",
        "main",
        "--head",
        "feature",
        "--format",
        "json",
    )

    files = json.loads(out)["files"]
    assert code == 0
    assert [file_change["path"] for file_change in files] == ["app.py"]
    assert [(s["key"], s["change"]) for s in files[0]["symbols"]] == [("greet", "modified")]


@needs_git
def test_cli_can_compare_two_commits_directly(capsys, repo):
    code, out, _ = run_cli(
        capsys,
        "changed-symbols",
        "--repo",
        str(repo),
        "--base",
        "main",
        "--head",
        "feature",
        "--no-merge-base",
        "--format",
        "json",
    )

    assert code == 0
    assert {file_change["path"] for file_change in json.loads(out)["files"]} == {
        "app.py",
        "other.py",
    }


@needs_git
def test_cli_reports_an_unknown_revision(capsys, repo):
    code, _, err = run_cli(capsys, "changed-symbols", "--repo", str(repo), "--base", "nope")

    assert code == 2
    assert "unknown revision" in err


@needs_git
def test_rename_detected_by_git_is_carried_through(capsys, repo):
    git(repo, "mv", "other.py", "renamed.py")
    git(repo, "commit", "--quiet", "--message", "rename")

    code, out, _ = run_cli(capsys, "changed-symbols", "--repo", str(repo), "--base", "HEAD~1")

    assert code == 0
    assert "renamed.py (renamed from other.py)" in out
    assert "no symbols changed" in out
