"""What does and does not count as a change to a symbol's code."""

from analysis.model import Part
from analysis.parsing import PythonAdapter
from analysis.parsing.fingerprint import fingerprint
from helpers import extract


def body(source: str, key: str = "f") -> str:
    return extract(source)[key].fingerprints[Part.BODY]


def test_comments_and_blank_lines_are_ignored():
    plain = """
        def f(a):
            total = a + 1
            return total
        """
    commented = """
        def f(a):
            # explain the step

            total = a + 1  # trailing note
            return total
        """

    assert body(plain) == body(commented)


def test_line_wrapping_is_ignored():
    one_line = """
        def f(a, b):
            return compute(a, b, flag=True)
        """
    wrapped = """
        def f(a, b):
            return compute(
                a,
                b,
                flag=True
            )
        """

    assert body(one_line) == body(wrapped)


def test_backslash_continuation_is_ignored():
    joined = """
        def f(a, b):
            return a + b
        """
    continued = """
        def f(a, b):
            return a + \\
                b
        """

    assert body(joined) == body(continued)


def test_indentation_width_is_ignored():
    four = "def f():\n    if x:\n        return 1\n"
    two = "def f():\n  if x:\n    return 1\n"

    assert body(four) == body(two)


def test_moving_a_statement_out_of_a_block_is_a_change():
    # Same tokens in the same order. Only the tree shape differs, which is why
    # the fingerprint hashes structure and not just a flat list of tokens.
    inside = """
        def f():
            if ready:
                start()
                finish()
        """
    outside = """
        def f():
            if ready:
                start()
            finish()
        """

    assert body(inside) != body(outside)


def test_operator_change_is_a_change():
    assert body("def f(a):\n    return a < 0\n") != body("def f(a):\n    return a <= 0\n")


def test_string_content_is_compared_byte_for_byte():
    assert body('def f():\n    return "a\\nb"\n') != body('def f():\n    return "x\\nb"\n')
    assert body('def f():\n    return "a b"\n') != body('def f():\n    return "a  b"\n')
    # Whitespace next to an escape sequence sits between two child nodes of the
    # string. It only survives because strings are hashed as raw text.
    assert body('def f():\n    return "a \\n b"\n') != body('def f():\n    return "a  \\n b"\n')


def test_format_spec_inside_f_string_is_a_change():
    assert body('def f(v):\n    return f"{v:>10}"\n') != body('def f(v):\n    return f"{v:>12}"\n')


def test_docstring_change_is_a_change():
    # A docstring is a real value at run time (``__doc__``), and doctests live
    # in it, so it is not treated like a comment.
    first = 'def f():\n    """Old."""\n    return 1\n'
    second = 'def f():\n    """New."""\n    return 1\n'

    assert body(first) != body(second)


def test_parts_are_fingerprinted_separately():
    before = extract("@cache\ndef f(a):\n    return a\n")["f"].fingerprints
    new_decorator = extract("@lru_cache\ndef f(a):\n    return a\n")["f"].fingerprints
    new_signature = extract("@cache\ndef f(a, b=2):\n    return a\n")["f"].fingerprints
    new_body = extract("@cache\ndef f(a):\n    return a * 2\n")["f"].fingerprints

    def differing(after):
        return {part for part in before if before[part] != after[part]}

    assert differing(new_decorator) == {Part.DECORATORS}
    assert differing(new_signature) == {Part.SIGNATURE}
    assert differing(new_body) == {Part.BODY}


def test_return_annotation_belongs_to_the_signature():
    before = extract("def f(a) -> int:\n    return a\n")["f"].fingerprints
    after = extract("def f(a) -> float:\n    return a\n")["f"].fingerprints

    assert before[Part.SIGNATURE] != after[Part.SIGNATURE]
    assert before[Part.BODY] == after[Part.BODY]


def test_comment_between_signature_and_body_is_ignored():
    before = extract("def f(a):\n    return a\n")["f"].fingerprints
    after = extract("def f(a):  # why\n    # more\n    return a\n")["f"].fingerprints

    assert before == after


def test_method_edit_does_not_change_the_class_fingerprint():
    before = extract("class C:\n    x = 1\n    def m(self):\n        return 1\n")
    after = extract("class C:\n    x = 1\n    def m(self):\n        return 2\n")

    assert before["C"].fingerprints == after["C"].fingerprints
    assert before["C.m"].fingerprints != after["C.m"].fingerprints


def test_adding_a_member_does_not_change_the_class_or_module_fingerprint():
    before = extract("class C:\n    def m(self):\n        return 1\n")
    after = extract(
        "class C:\n    def m(self):\n        return 1\n    def n(self):\n        return 2\n"
        "def helper():\n    pass\n"
    )

    assert before["C"].fingerprints == after["C"].fingerprints
    assert before["<module>"].fingerprints == after["<module>"].fingerprints


def test_position_of_a_nested_definition_is_part_of_a_function_body():
    define_first = """
        def f():
            def helper():
                return 1
            value = helper()
            return value
        """
    use_first = """
        def f():
            value = helper()
            def helper():
                return 1
            return value
        """

    assert body(define_first) != body(use_first)


def test_very_deep_expressions_do_not_overflow_the_stack():
    deep = "def f():\n    return " + " + ".join(["1"] * 20_000) + "\n"

    assert body(deep) != body(deep.replace("1 + 1", "1 + 2", 1))


def test_text_between_child_nodes_is_hashed():
    # In the grammar, the `>10` of a format spec is not a node of its own: it is
    # text lying between the children of its parent. With strings opened up
    # (no atomic types), only the gap hashing can see it change.
    def opened_up(source: bytes) -> str:
        root = PythonAdapter().parse(source).tree.root_node
        return fingerprint([root], source, ignored_types=frozenset(), atomic_types=frozenset())

    assert opened_up(b'x = f"{v:>10}"\n') != opened_up(b'x = f"{v:>12}"\n')
    assert opened_up(b"x = [1,\n     2]\n") == opened_up(b"x = [1, 2]\n")
