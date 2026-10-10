from types import CodeType

from analysis.model import MODULE_NAME, Span, SymbolKind
from analysis.parsing import PythonAdapter
from helpers import clean, extract

SAMPLE = """
import functools

LIMIT = 10


def plain(a, b=1):
    return a + b


@functools.cache
def decorated():
    return 1


async def fetch[T](item: T) -> T:
    return item


def outer(x):
    def inner(y):
        class Local:
            def method(self):
                return y
        return Local
    return inner


class Shape(object):
    sides = 0

    def area(self):
        return 0

    @staticmethod
    def make():
        return Shape()

    class Meta:
        def describe(self):
            return "meta"
"""


def test_kinds_and_qualified_names():
    kinds = {key: extracted.symbol.kind for key, extracted in extract(SAMPLE).items()}

    assert kinds == {
        MODULE_NAME: SymbolKind.MODULE,
        "plain": SymbolKind.FUNCTION,
        "decorated": SymbolKind.FUNCTION,
        "fetch": SymbolKind.FUNCTION,
        "outer": SymbolKind.FUNCTION,
        "outer.<locals>.inner": SymbolKind.FUNCTION,
        "outer.<locals>.inner.<locals>.Local": SymbolKind.CLASS,
        "outer.<locals>.inner.<locals>.Local.method": SymbolKind.METHOD,
        "Shape": SymbolKind.CLASS,
        "Shape.area": SymbolKind.METHOD,
        "Shape.make": SymbolKind.METHOD,
        "Shape.Meta": SymbolKind.CLASS,
        "Shape.Meta.describe": SymbolKind.METHOD,
    }


def test_qualified_names_match_what_python_itself_reports():
    """Compare against CPython: every code object records its ``__qualname__``."""

    def compiled_names(code: CodeType) -> set[str]:
        names: set[str] = set()
        for constant in code.co_consts:
            if isinstance(constant, CodeType):
                if not constant.co_name.startswith("<"):  # skip lambdas, genexprs
                    names.add(constant.co_qualname)
                names |= compiled_names(constant)
        return names

    expected = compiled_names(compile(clean(SAMPLE), "sample.py", "exec"))
    # Type parameters make the compiler emit a helper scope with its own name.
    expected = {name for name in expected if "<generic parameters" not in name}

    assert set(extract(SAMPLE)) - {MODULE_NAME} == expected


def test_span_includes_decorators():
    symbols = extract(
        """
        x = 1

        @first
        @second(arg)
        def target():
            return 1
        """
    )

    assert symbols["target"].symbol.span == Span(3, 6)


def test_parent_keys_form_the_nesting_chain():
    symbols = extract(SAMPLE)

    assert symbols[MODULE_NAME].parent_key is None
    assert symbols["plain"].parent_key == MODULE_NAME
    assert symbols["Shape.area"].parent_key == "Shape"
    assert symbols["outer.<locals>.inner"].parent_key == "outer"


def test_owned_lines_exclude_nested_definitions_and_blank_lines():
    symbols = extract(
        """
        class Box:
            size = 1

            def get(self):
                return self.size

            label = "box"
        """
    )

    assert symbols["Box"].owned_lines == {1, 2, 7}
    assert symbols["Box.get"].owned_lines == {4, 5}
    assert symbols[MODULE_NAME].owned_lines == set()


def test_repeated_names_get_ordinals():
    symbols = extract(
        """
        class Account:
            @property
            def balance(self):
                return self._balance

            @balance.setter
            def balance(self, value):
                self._balance = value

        if FAST:
            def run(): return 1
        else:
            def run(): return 2
        """
    )

    assert symbols["Account.balance"].symbol.span == Span(2, 4)
    assert symbols["Account.balance#2"].symbol.span == Span(6, 8)
    assert symbols["Account.balance#2"].symbol.ordinal == 2
    assert {"run", "run#2"} <= set(symbols)


def test_definitions_inside_compound_statements_are_found():
    symbols = extract(
        """
        try:
            import fast
        except ImportError:
            def fallback():
                pass

        with context():
            for item in items:
                while True:
                    class Deep:
                        pass

        match command:
            case "go":
                def handler():
                    pass
        """
    )

    assert {"fallback", "Deep", "handler"} <= set(symbols)
    assert symbols["Deep"].parent_key == MODULE_NAME


def test_module_span_covers_the_whole_file():
    assert extract("a = 1\nb = 2\n")[MODULE_NAME].symbol.span == Span(1, 2)
    assert extract("a = 1\nb = 2")[MODULE_NAME].symbol.span == Span(1, 2)


def test_empty_file_has_only_a_module():
    adapter = PythonAdapter()

    symbols = adapter.symbols(adapter.parse(b""), "empty.py")

    assert [extracted.symbol.qualified_name for extracted in symbols] == [MODULE_NAME]
    assert symbols[0].symbol.span == Span(1, 1)


def test_syntax_errors_are_reported_but_do_not_stop_extraction():
    adapter = PythonAdapter()
    source = clean(
        """
        def good():
            return 1

        def broken(:
            return 2

        def also_good():
            return 3
        """
    ).encode()

    parsed = adapter.parse(source)
    names = {extracted.symbol.qualified_name for extracted in adapter.symbols(parsed, "bad.py")}

    assert parsed.has_errors
    assert {"good", "also_good"} <= names


def test_non_utf8_bytes_do_not_crash():
    adapter = PythonAdapter()

    symbols = adapter.symbols(adapter.parse(b"def f():\n    return '\xff\xfe'\n"), "latin.py")

    assert "f" in {extracted.symbol.qualified_name for extracted in symbols}


def test_definitions_far_down_a_long_file_have_correct_spans():
    # Guards the workaround in `_line_span`: tree-sitter 0.26.0 mishandles row
    # and column numbers above 256 when they are read as attributes.
    filler = "".join(f"value_{number} = {number}\n" for number in range(5_000))
    source = filler + "def last(argument):\n    return argument\n"
    adapter = PythonAdapter()

    for _ in range(20):
        symbols = adapter.symbols(adapter.parse(source.encode()), "long.py")

    assert symbols[-1].symbol.qualified_name == "last"
    assert symbols[-1].symbol.span == Span(5_001, 5_002)
