"""Python support, built on the Tree-sitter Python grammar."""

from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from analysis.model import MODULE_NAME, ExtractedSymbol, Part, Span, Symbol, SymbolKind
from analysis.parsing.adapter import ParsedSource
from analysis.parsing.fingerprint import fingerprint

_LANGUAGE = Language(tree_sitter_python.language())

_DEFINITION_TYPES = frozenset({"function_definition", "class_definition"})
_IGNORED_TYPES = frozenset({"comment", "line_continuation"})
_ATOMIC_TYPES = frozenset({"string"})

# Simple statements cannot contain a `def` or `class`, so the search for
# definitions does not look inside them. This is only an optimisation: any node
# type missing from this list is still searched.
_NO_DEFINITIONS_INSIDE = frozenset(
    {
        "assert_statement",
        "break_statement",
        "comment",
        "continue_statement",
        "delete_statement",
        "exec_statement",
        "expression_statement",
        "future_import_statement",
        "global_statement",
        "import_from_statement",
        "import_statement",
        "nonlocal_statement",
        "pass_statement",
        "print_statement",
        "raise_statement",
        "return_statement",
        "type_alias_statement",
    }
)

_NESTED_MARKER = b"<nested-definition>"


@dataclass(slots=True)
class _Scope:
    """A definition found during the walk, before its facts are computed."""

    kind: SymbolKind
    qualified_name: str
    ordinal: int
    outer: Node
    """The whole definition, including decorators when there are any."""
    definition: Node | None
    """The ``def``/``class`` node itself; None for the module."""
    parent: int | None
    children: list[int] = field(default_factory=list)

    @property
    def key(self) -> str:
        if self.ordinal == 1:
            return self.qualified_name
        return f"{self.qualified_name}#{self.ordinal}"


class PythonAdapter:
    name = "python"
    extensions: tuple[str, ...] = (".py", ".pyi")

    def parse(self, source: bytes) -> ParsedSource:
        # A Parser is cheap to create and is not safe to share between threads,
        # so each call gets its own. The compiled grammar is shared.
        return ParsedSource(source=source, tree=Parser(_LANGUAGE).parse(source))

    def symbols(self, parsed: ParsedSource, path: str) -> list[ExtractedSymbol]:
        scopes = _collect_scopes(parsed)
        total_lines = _count_lines(parsed.source)
        blank_lines = _blank_lines(parsed.source)
        spans = [
            Span(1, total_lines) if scope.definition is None else _line_span(scope.outer)
            for scope in scopes
        ]

        extracted: list[ExtractedSymbol] = []
        for index, scope in enumerate(scopes):
            span = spans[index]
            owned = set(range(span.start_line, span.end_line + 1))
            # A blank line belongs to nobody. Otherwise adding a method would
            # report its class as touched, just for the empty line around it.
            owned.difference_update(blank_lines)
            for child in scope.children:
                owned.difference_update(range(spans[child].start_line, spans[child].end_line + 1))

            extracted.append(
                ExtractedSymbol(
                    symbol=Symbol(
                        path=path,
                        qualified_name=scope.qualified_name,
                        kind=scope.kind,
                        span=span,
                        ordinal=scope.ordinal,
                    ),
                    parent_key=None if scope.parent is None else scopes[scope.parent].key,
                    owned_lines=frozenset(owned),
                    fingerprints=_fingerprints(scope, scopes, parsed.source),
                )
            )
        return extracted


def _collect_scopes(parsed: ParsedSource) -> list[_Scope]:
    """Find every definition, in source order, with its enclosing definition.

    Index 0 is always the module. Qualified names follow Python's own
    ``__qualname__`` rules, so ``Cart.total`` is a method and
    ``outer.<locals>.inner`` is a function defined inside ``outer``.
    """
    root = parsed.tree.root_node
    scopes = [_Scope(SymbolKind.MODULE, MODULE_NAME, 1, root, None, None)]
    seen: dict[str, int] = {}

    # Children are pushed in reverse so they pop in source order. Source order
    # matters because ordinals are assigned as definitions are met.
    stack: list[tuple[Node, int]] = [(child, 0) for child in reversed(root.children)]
    while stack:
        node, owner = stack.pop()

        definition: Node | None = None
        if node.type == "decorated_definition":
            definition = node.child_by_field_name("definition")
        elif node.type in _DEFINITION_TYPES:
            definition = node

        name = _definition_name(definition, parsed.source)
        if definition is not None and name is not None:
            parent = scopes[owner]
            qualified_name = _qualify(parent, name)
            ordinal = seen.get(qualified_name, 0) + 1
            seen[qualified_name] = ordinal

            index = len(scopes)
            scopes.append(
                _Scope(
                    kind=_kind(definition, parent),
                    qualified_name=qualified_name,
                    ordinal=ordinal,
                    outer=node,
                    definition=definition,
                    parent=owner,
                )
            )
            parent.children.append(index)

            body = definition.child_by_field_name("body")
            if body is not None:
                stack.extend((child, index) for child in reversed(body.children))
            continue

        if node.type not in _NO_DEFINITIONS_INSIDE and node.child_count:
            stack.extend((child, owner) for child in reversed(node.children))

    return scopes


def _definition_name(definition: Node | None, source: bytes) -> str | None:
    if definition is None or definition.type not in _DEFINITION_TYPES:
        return None
    name = definition.child_by_field_name("name")
    if name is None:
        return None
    text = source[name.start_byte : name.end_byte].decode("utf-8", errors="replace")
    return text or None


def _qualify(parent: _Scope, name: str) -> str:
    if parent.kind is SymbolKind.MODULE:
        return name
    if parent.kind is SymbolKind.CLASS:
        return f"{parent.qualified_name}.{name}"
    return f"{parent.qualified_name}.<locals>.{name}"


def _kind(definition: Node, parent: _Scope) -> SymbolKind:
    if definition.type == "class_definition":
        return SymbolKind.CLASS
    if parent.kind is SymbolKind.CLASS:
        return SymbolKind.METHOD
    return SymbolKind.FUNCTION


def _fingerprints(scope: _Scope, scopes: list[_Scope], source: bytes) -> dict[Part, str]:
    nested_ids = frozenset(scopes[child].outer.id for child in scope.children)
    # Inside a function, a nested definition is a statement that runs in order,
    # so its position is part of the function's behaviour and leaves a marker.
    # In a class or module it is a member: adding one is reported as that member
    # being added, not as the container changing.
    is_function = scope.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD)
    marker = _NESTED_MARKER if is_function else None

    def hash_nodes(nodes: list[Node]) -> str:
        return fingerprint(
            nodes,
            source,
            ignored_types=_IGNORED_TYPES,
            atomic_types=_ATOMIC_TYPES,
            nested_ids=nested_ids,
            nested_marker=marker,
        )

    definition = scope.definition
    if definition is None:
        return {Part.BODY: hash_nodes([scope.outer])}

    body = definition.child_by_field_name("body")
    decorators = [child for child in scope.outer.children if child.type == "decorator"]
    signature = [child for child in definition.children if body is None or child.id != body.id]
    return {
        Part.DECORATORS: hash_nodes(decorators),
        Part.SIGNATURE: hash_nodes(signature),
        Part.BODY: hash_nodes([] if body is None else [body]),
    }


def _line_span(node: Node) -> Span:
    # Points are read by index, not as `.row` and `.column`. In tree-sitter
    # 0.26.0 those two attributes hand back a reference they do not own, which
    # frees the number while it is still in use once it exceeds 256 (line 258
    # onwards). Indexing goes through the ordinary tuple code and is safe.
    start_row, _ = node.start_point
    end_row, end_column = node.end_point
    start = start_row + 1
    end = end_row + 1
    # A node that ends at column 0 stops just before that line begins.
    if end_column == 0 and end > start:
        end -= 1
    return Span(start, end)


def _blank_lines(source: bytes) -> set[int]:
    return {number for number, line in enumerate(source.split(b"\n"), start=1) if not line.strip()}


def _count_lines(source: bytes) -> int:
    if not source:
        return 1
    return source.count(b"\n") + (0 if source.endswith(b"\n") else 1)
