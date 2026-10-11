"""End-to-end behaviour of change detection on single-file changes."""

import pytest

from analysis.diff import parse_unified_diff
from analysis.model import MODULE_NAME, ChangeKind, FileStatus, Part, SkipReason, Span
from analysis.sources import MappingSnapshot
from analysis.symbols import Limits, detect_changed_symbols
from helpers import PATH, analyse, analyse_file, clean, unified_diff

BASE = """
import math

RATE = 0.2


def area(radius):
    return math.pi * radius ** 2


def price(amount):
    if amount < 0:
        raise ValueError("negative")
    return amount * (1 - RATE)


class Cart:
    currency = "EUR"

    def __init__(self):
        self.items = []

    def total(self):
        return sum(price(item) for item in self.items)
"""


def kinds(changes):
    return {key: change.change for key, change in changes.items()}


# --- modified -------------------------------------------------------------


def test_body_edit_reports_only_that_function():
    changes = analyse(BASE, BASE.replace("amount * (1 - RATE)", "amount * (1 + RATE)"))

    assert kinds(changes) == {"price": ChangeKind.MODIFIED}
    assert changes["price"].parts == (Part.BODY,)
    assert changes["price"].touched_base_lines == (13,)
    assert changes["price"].touched_head_lines == (13,)


def test_lines_removed_without_replacement_still_modify_the_function():
    # The classic miss: a tool that only looks at added lines sees nothing here,
    # because this change adds no lines at all.
    head = BASE.replace('    if amount < 0:\n        raise ValueError("negative")\n', "")

    changes = analyse(BASE, head)

    assert kinds(changes) == {"price": ChangeKind.MODIFIED}
    assert changes["price"].touched_base_lines == (11, 12)
    assert changes["price"].touched_head_lines == ()


def test_signature_edit():
    changes = analyse(BASE, BASE.replace("def price(amount):", "def price(amount, tax=0):"))

    assert changes["price"].parts == (Part.SIGNATURE,)


def test_decorator_added():
    changes = analyse(BASE, BASE.replace("def area(radius):", "@cache\ndef area(radius):"))

    assert kinds(changes) == {"area": ChangeKind.MODIFIED}
    assert changes["area"].parts == (Part.DECORATORS,)
    assert changes["area"].base.span == Span(6, 7)
    assert changes["area"].head.span == Span(6, 8)


def test_decorator_argument_changed():
    base = "@retry(times=3)\ndef call():\n    return 1\n"
    head = "@retry(times=5)\ndef call():\n    return 1\n"

    assert analyse(base, head)["call"].parts == (Part.DECORATORS,)


def test_method_edit_does_not_report_the_class():
    changes = analyse(BASE, BASE.replace("return sum(price(item)", "return max(price(item)"))

    assert kinds(changes) == {"Cart.total": ChangeKind.MODIFIED}


def test_class_attribute_edit_reports_the_class_body():
    changes = analyse(BASE, BASE.replace('currency = "EUR"', 'currency = "RON"'))

    assert kinds(changes) == {"Cart": ChangeKind.MODIFIED}
    assert changes["Cart"].parts == (Part.BODY,)


def test_base_class_edit_reports_the_class_signature():
    changes = analyse(BASE, BASE.replace("class Cart:", "class Cart(Basket):"))

    assert kinds(changes) == {"Cart": ChangeKind.MODIFIED}
    assert changes["Cart"].parts == (Part.SIGNATURE,)


def test_top_level_code_is_reported_as_the_module():
    changes = analyse(BASE, BASE.replace("RATE = 0.2", "RATE = 0.25"))

    assert kinds(changes) == {MODULE_NAME: ChangeKind.MODIFIED}


def test_import_edit_is_reported_as_the_module():
    changes = analyse(BASE, BASE.replace("import math", "import math\nimport os"))

    assert kinds(changes) == {MODULE_NAME: ChangeKind.MODIFIED}


def test_unchanged_functions_below_an_edit_are_not_reported():
    # Everything under the new lines shifts down, so their line numbers differ
    # between base and head, yet none of them changed.
    head = BASE.replace("RATE = 0.2", "RATE = 0.2\nEXTRA = 1\nMORE = 2")

    assert set(analyse(BASE, head)) == {MODULE_NAME}


# --- added and deleted ----------------------------------------------------


def test_added_function():
    changes = analyse(BASE, BASE + "\n\ndef refund(amount):\n    return -amount\n")

    assert kinds(changes) == {"refund": ChangeKind.ADDED}
    assert changes["refund"].base is None
    assert changes["refund"].head.span == Span(26, 27)


def test_deleted_function():
    head = BASE.replace("def area(radius):\n    return math.pi * radius ** 2\n\n\n", "")

    changes = analyse(BASE, head)

    assert kinds(changes) == {"area": ChangeKind.DELETED}
    assert changes["area"].head is None
    assert changes["area"].touched_base_lines == (6, 7)


def test_added_method_does_not_report_the_class():
    head = BASE + "\n    def clear(self):\n        self.items.clear()\n"

    assert kinds(analyse(BASE, head)) == {"Cart.clear": ChangeKind.ADDED}


def test_deleted_class_reports_the_class_and_its_methods():
    head = BASE[: BASE.index("class Cart:")]

    assert kinds(analyse(BASE, head)) == {
        "Cart": ChangeKind.DELETED,
        "Cart.__init__": ChangeKind.DELETED,
        "Cart.total": ChangeKind.DELETED,
    }


def test_renamed_function_is_a_deletion_plus_an_addition():
    # Documented limitation: nothing links the two, but both ends are reported,
    # so callers of the old name are still found.
    changes = analyse(BASE, BASE.replace("def area(radius):", "def circle_area(radius):"))

    assert kinds(changes) == {"area": ChangeKind.DELETED, "circle_area": ChangeKind.ADDED}


# --- nested definitions ---------------------------------------------------

NESTED = """
def outer(values):
    def keep(value):
        return value > 0

    return [value for value in values if keep(value)]


def factory():
    class Handler:
        def run(self):
            return 1

    return Handler()
"""


def test_nested_function_edit_also_reports_the_enclosing_function():
    changes = analyse(NESTED, NESTED.replace("value > 0", "value >= 0"))

    assert kinds(changes) == {
        "outer": ChangeKind.MODIFIED,
        "outer.<locals>.keep": ChangeKind.MODIFIED,
    }
    assert changes["outer"].parts == (Part.NESTED,)
    assert changes["outer.<locals>.keep"].parts == (Part.BODY,)


def test_method_of_a_local_class_reports_the_function_but_not_the_class():
    changes = analyse(NESTED, NESTED.replace("return 1", "return 2"))

    assert kinds(changes) == {
        "factory": ChangeKind.MODIFIED,
        "factory.<locals>.Handler.run": ChangeKind.MODIFIED,
    }
    assert changes["factory"].parts == (Part.NESTED,)


def test_added_nested_function_modifies_the_enclosing_function():
    head = NESTED.replace(
        "    return [value for",
        "    def drop(value):\n        return False\n\n    return [value for",
    )

    changes = analyse(NESTED, head)

    assert kinds(changes) == {
        "outer": ChangeKind.MODIFIED,
        "outer.<locals>.drop": ChangeKind.ADDED,
    }
    assert changes["outer"].parts == (Part.BODY, Part.NESTED)


def test_edit_in_outer_body_does_not_report_the_nested_function():
    changes = analyse(NESTED, NESTED.replace("if keep(value)]", "if not keep(value)]"))

    assert kinds(changes) == {"outer": ChangeKind.MODIFIED}
    assert changes["outer"].parts == (Part.BODY,)


# --- cosmetic -------------------------------------------------------------


def test_comment_only_edit_is_cosmetic():
    head = BASE.replace("    return math.pi", "    # circle area\n    return math.pi")

    changes = analyse(BASE, head)

    assert kinds(changes) == {"area": ChangeKind.COSMETIC}
    assert changes["area"].parts == ()
    assert changes["area"].touched_head_lines == (7,)


def test_rewrapped_call_is_cosmetic():
    base = "def f(a, b):\n    return compute(a, b)\n"
    head = "def f(a, b):\n    return compute(\n        a, b\n    )\n"

    assert kinds(analyse(base, head)) == {"f": ChangeKind.COSMETIC}


def test_moved_function_is_cosmetic():
    # The diff shows the function removed in one place and added in another.
    area = "def area(radius):\n    return math.pi * radius ** 2\n\n\n"
    head = clean(BASE).replace(area, "") + "\n\n" + area.rstrip("\n") + "\n"

    assert kinds(analyse(BASE, head)) == {"area": ChangeKind.COSMETIC}


def test_blank_line_edits_report_nothing():
    head = BASE.replace("RATE = 0.2\n", "RATE = 0.2\n\n\n")

    assert analyse(BASE, head) == {}


def test_cosmetic_edit_in_nested_function_does_not_modify_the_outer_one():
    head = NESTED.replace(
        "        return value > 0", "        # positive only\n        return value > 0"
    )

    assert kinds(analyse(NESTED, head)) == {"outer.<locals>.keep": ChangeKind.COSMETIC}


# --- repeated names -------------------------------------------------------


def test_only_the_edited_setter_is_reported():
    base = """
        class Account:
            @property
            def balance(self):
                return self._balance

            @balance.setter
            def balance(self, value):
                self._balance = value
        """

    changes = analyse(base, base.replace("self._balance = value", "self._balance = max(value, 0)"))

    assert kinds(changes) == {"Account.balance#2": ChangeKind.MODIFIED}


# --- whole files ----------------------------------------------------------


def test_added_file_reports_every_symbol_as_added():
    change = analyse_file(None, "X = 1\n\ndef f():\n    return X\n")

    assert change.status is FileStatus.ADDED
    assert {symbol.key: symbol.change for symbol in change.symbols} == {
        MODULE_NAME: ChangeKind.ADDED,
        "f": ChangeKind.ADDED,
    }


def test_deleted_file_reports_every_symbol_as_deleted():
    change = analyse_file("class A:\n    def m(self):\n        pass\n", None)

    assert change.status is FileStatus.DELETED
    assert {symbol.key: symbol.change for symbol in change.symbols} == {
        MODULE_NAME: ChangeKind.DELETED,
        "A": ChangeKind.DELETED,
        "A.m": ChangeKind.DELETED,
    }


def test_renamed_and_edited_file_pairs_symbols_across_paths():
    change = analyse_file(
        "def f():\n    return 1\n\ndef g():\n    return 2\n",
        "def f():\n    return 1\n\ndef g():\n    return 3\n",
        path="new/name.py",
        old_path="old/name.py",
    )

    assert change.status is FileStatus.RENAMED
    assert change.old_path == "old/name.py"
    (symbol,) = change.symbols
    assert symbol.key == "g" and symbol.change is ChangeKind.MODIFIED
    assert symbol.base.path == "old/name.py"
    assert symbol.head.path == "new/name.py"


def test_symbols_are_listed_in_file_order():
    head = (
        BASE.replace("RATE = 0.2", "RATE = 0.3")
        .replace("radius ** 2", "radius ** 3")
        .replace("return sum(", "return min(")
    )

    assert [symbol.key for symbol in analyse_file(BASE, head).symbols] == [
        MODULE_NAME,
        "area",
        "Cart.total",
    ]


# --- files that are not analysed ------------------------------------------


def test_unsupported_language_is_listed_but_skipped():
    change = analyse_file("a\n", "b\n", path="README.md")

    assert change.skipped is SkipReason.UNSUPPORTED_LANGUAGE
    assert change.language is None
    assert change.symbols == ()


def test_binary_file_is_skipped():
    diff = "diff --git a/x.py b/x.py\nBinary files a/x.py and b/x.py differ\n"

    change_set = detect_changed_symbols(
        parse_unified_diff(diff), MappingSnapshot({}), MappingSnapshot({})
    )

    assert change_set.file("x.py").skipped is SkipReason.BINARY


def test_file_over_the_size_limit_is_skipped():
    base, head = "a = 1\n", "a = 2\n" + "# padding\n" * 50
    change_set = detect_changed_symbols(
        parse_unified_diff(unified_diff(base, head)),
        MappingSnapshot({PATH: base}),
        MappingSnapshot({PATH: head}),
        limits=Limits(max_file_bytes=100),
    )

    assert change_set.file(PATH).skipped is SkipReason.TOO_LARGE


def test_file_missing_from_a_snapshot_is_skipped():
    base, head = "a = 1\n", "a = 2\n"
    change_set = detect_changed_symbols(
        parse_unified_diff(unified_diff(base, head)),
        MappingSnapshot({PATH: base}),
        MappingSnapshot({}),
    )

    assert change_set.file(PATH).skipped is SkipReason.MISSING_SOURCE


def test_syntax_errors_are_flagged_on_the_file():
    change = analyse_file("def f():\n    return 1\n", "def f(:\n    return 1\n")

    assert change.syntax_errors


def test_json_shape():
    change = analyse_file(BASE, BASE.replace("amount * (1 - RATE)", "amount * (1 + RATE)"))

    assert change.to_dict() == {
        "path": PATH,
        "old_path": None,
        "status": "modified",
        "language": "python",
        "skipped": None,
        "syntax_errors": False,
        "symbols": [
            {
                "key": "price",
                "qualified_name": "price",
                "kind": "function",
                "change": "modified",
                "parts": ["body"],
                "base_span": {"start_line": 10, "end_line": 13},
                "head_span": {"start_line": 10, "end_line": 13},
                "touched_base_lines": [13],
                "touched_head_lines": [13],
            }
        ],
    }


# --- limits ---------------------------------------------------------------


def three_python_files_and_a_readme():
    files = ["a.py", "notes.md", "b.py", "c.py"]
    diff = "".join(unified_diff("x = 1\n", "x = 2\n", path=name) for name in files)
    base = MappingSnapshot(dict.fromkeys(files, "x = 1\n"))
    head = MappingSnapshot(dict.fromkeys(files, "x = 2\n"))
    return parse_unified_diff(diff), base, head


def test_file_limit_counts_only_files_that_are_parsed():
    diffs, base, head = three_python_files_and_a_readme()

    change_set = detect_changed_symbols(diffs, base, head, limits=Limits(max_files=2))

    # The Markdown file is skipped anyway, so it does not use up the allowance.
    assert [(change.path, change.skipped) for change in change_set] == [
        ("a.py", None),
        ("notes.md", SkipReason.UNSUPPORTED_LANGUAGE),
        ("b.py", None),
        ("c.py", SkipReason.TOO_MANY_FILES),
    ]
    assert not change_set.complete


def test_time_budget_stops_between_files():
    diffs, base, head = three_python_files_and_a_readme()
    # A fake clock makes the test exact and instant: every reading is one second
    # after the previous one.
    readings = iter(range(100))

    change_set = detect_changed_symbols(
        diffs,
        base,
        head,
        limits=Limits(time_budget_seconds=2.5),
        clock=lambda: float(next(readings)),
    )

    assert [change.skipped for change in change_set] == [
        None,
        SkipReason.UNSUPPORTED_LANGUAGE,
        SkipReason.TIME_BUDGET_EXCEEDED,
        SkipReason.TIME_BUDGET_EXCEEDED,
    ]
    assert not change_set.complete


def test_result_is_complete_when_only_unanalysable_files_were_skipped():
    diffs, base, head = three_python_files_and_a_readme()

    change_set = detect_changed_symbols(diffs, base, head)

    assert change_set.complete
    assert change_set.to_dict()["complete"] is True


@pytest.mark.parametrize("limits", [Limits(max_file_bytes=3), Limits(max_files=1)])
def test_any_limit_that_hides_code_makes_the_result_incomplete(limits):
    diffs, base, head = three_python_files_and_a_readme()

    assert not detect_changed_symbols(diffs, base, head, limits=limits).complete


def test_missing_source_makes_the_result_incomplete():
    diffs, base, _ = three_python_files_and_a_readme()

    assert not detect_changed_symbols(diffs, base, MappingSnapshot({})).complete
