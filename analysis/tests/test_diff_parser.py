import pytest

from analysis.diff import DiffParseError, parse_unified_diff
from analysis.model import FileStatus

# Real output of `git diff --find-renames --unified=0` on a small repository.
GIT_DIFF = """\
diff --git a/b.bin b/b.bin
index 88768ef..f68ed80 100644
Binary files a/b.bin and b/b.bin differ
diff --git a/gone.py b/gone.py
deleted file mode 100644
index 0536001..0000000
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def gone():
-    pass
diff --git a/new.py b/new.py
new file mode 100755
index 0000000..0f86851
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+new=1
diff --git a/nonl.py b/nonl.py
index b41e3ee..8161f74 100644
--- a/nonl.py
+++ b/nonl.py
@@ -1 +1 @@
-print(1)
\\ No newline at end of file
+print(2)
\\ No newline at end of file
diff --git a/sp ace.py b/pkg/moved.py
similarity index 100%
rename from sp ace.py
rename to pkg/moved.py
diff --git a/edit.py b/edit.py
index 1111111..2222222 100644
--- a/edit.py
+++ b/edit.py
@@ -3 +2,0 @@ def a():
-    x = 1
@@ -10,0 +10,2 @@ def b():
+    y = 2
+    z = 3
@@ -20,2 +21 @@ def c():
-    old = 1
-    older = 2
+    new = 1
"""


def by_path(text: str):
    return {diff.path: diff for diff in parse_unified_diff(text)}


def test_statuses_and_paths():
    diffs = by_path(GIT_DIFF)

    assert diffs["gone.py"].status is FileStatus.DELETED
    assert diffs["gone.py"].new_path is None
    assert diffs["new.py"].status is FileStatus.ADDED
    assert diffs["new.py"].old_path is None
    assert diffs["nonl.py"].status is FileStatus.MODIFIED
    assert diffs["pkg/moved.py"].status is FileStatus.RENAMED
    assert diffs["pkg/moved.py"].old_path == "sp ace.py"


def test_binary_files_are_flagged_and_have_no_lines():
    binary = by_path(GIT_DIFF)["b.bin"]

    assert binary.is_binary
    assert not binary.added_lines and not binary.removed_lines


def test_each_side_is_numbered_against_its_own_file():
    edit = by_path(GIT_DIFF)["edit.py"]

    # Removed lines use base numbering, added lines use head numbering. The two
    # drift apart as soon as a hunk adds or removes a different number of lines.
    assert edit.removed_lines == {3, 20, 21}
    assert edit.added_lines == {10, 11, 21}


def test_whole_file_additions_and_deletions():
    diffs = by_path(GIT_DIFF)

    assert diffs["new.py"].added_lines == {1}
    assert diffs["gone.py"].removed_lines == {1, 2}


def test_missing_final_newline_marker_is_not_a_line():
    nonl = by_path(GIT_DIFF)["nonl.py"]

    assert nonl.removed_lines == {1}
    assert nonl.added_lines == {1}


def test_pure_rename_has_no_lines():
    moved = by_path(GIT_DIFF)["pkg/moved.py"]

    assert not moved.added_lines and not moved.removed_lines


def test_quoted_paths_are_unescaped():
    # Without core.quotepath=false, git writes non-ASCII paths as octal escapes.
    text = (
        'diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"\n'
        '--- "a/caf\\303\\251.py"\n'
        '+++ "b/caf\\303\\251.py"\n'
        "@@ -1 +1 @@\n"
        "-a = 1\n"
        "+a = 2\n"
    )

    (diff,) = parse_unified_diff(text)

    assert diff.path == "café.py"
    assert diff.status is FileStatus.MODIFIED


def test_diff_without_git_header():
    text = "--- a/x.py\n+++ b/x.py\n@@ -1 +1,2 @@\n-a\n+b\n+c\n"

    (diff,) = parse_unified_diff(text)

    assert diff.path == "x.py"
    assert diff.removed_lines == {1}
    assert diff.added_lines == {1, 2}


def test_empty_input_means_no_changes():
    assert parse_unified_diff("") == []


def test_hunk_that_contradicts_its_header_is_rejected():
    text = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n-b\n-c\n+d\n"

    with pytest.raises(DiffParseError):
        parse_unified_diff(text)


def test_escaped_backslash_and_quote_in_quoted_path():
    text = (
        'diff --git "a/we\\\\ird\\"name\\t.py" "b/we\\\\ird\\"name\\t.py"\n'
        '--- "a/we\\\\ird\\"name\\t.py"\n'
        '+++ "b/we\\\\ird\\"name\\t.py"\n'
        "@@ -1 +1 @@\n"
        "-a = 1\n"
        "+a = 2\n"
    )

    (diff,) = parse_unified_diff(text)

    assert diff.path == 'we\\ird"name\t.py'
