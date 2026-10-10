"""Structural fingerprints of syntax trees.

A fingerprint is a hash of what the code *is*, not how it is laid out. Two
pieces of code get the same fingerprint when they have the same tree shape and
the same tokens, even if comments, blank lines, indentation width or line
wrapping differ. Change detection compares fingerprints to tell a real edit from
a cosmetic one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from tree_sitter import Node

_OPEN = b"\x01"
_CLOSE = b"\x02"
_SEPARATOR = b"\x00"
_LAYOUT_BYTES = b" \t\r\n\f\\"


def fingerprint(
    roots: Iterable[Node],
    source: bytes,
    *,
    ignored_types: frozenset[str],
    atomic_types: frozenset[str],
    nested_ids: frozenset[int] = frozenset(),
    nested_marker: bytes | None = None,
) -> str:
    """Hash the subtrees under ``roots`` in source order.

    ``ignored_types`` are dropped entirely (comments). ``atomic_types`` are hashed
    as raw text without looking inside (string literals, where every byte counts).
    Nodes whose id is in ``nested_ids`` are definitions that have fingerprints of
    their own: they are replaced by ``nested_marker``, or dropped when it is None.

    The walk uses an explicit stack. Source files can contain expressions nested
    thousands of levels deep (a long chain of ``+``), which would overflow
    Python's call stack if this were written recursively.
    """
    digest = hashlib.blake2b(digest_size=16)
    stack: list[Node | None] = list(reversed(list(roots)))

    while stack:
        node = stack.pop()
        if node is None:
            digest.update(_CLOSE)
            continue
        if node.type in ignored_types:
            continue
        if node.id in nested_ids:
            if nested_marker is not None:
                digest.update(nested_marker)
            continue

        # The open/close markers encode the tree shape. Without them, moving a
        # statement into or out of an `if` block would hash the same, because
        # Python expresses that nesting through indentation rather than tokens.
        digest.update(_OPEN)
        digest.update(node.type.encode())
        digest.update(_SEPARATOR)

        children = node.children
        if not children or node.type in atomic_types:
            digest.update(source[node.start_byte : node.end_byte])
            digest.update(_CLOSE)
            continue

        # A node's children do not always cover all of its text. Hash whatever
        # falls between them, minus layout, so no token can change unnoticed.
        position = node.start_byte
        for child in children:
            _update_with_gap(digest, source[position : child.start_byte])
            position = child.end_byte
        _update_with_gap(digest, source[position : node.end_byte])

        stack.append(None)
        stack.extend(reversed(children))

    return digest.hexdigest()


def _update_with_gap(digest: hashlib.blake2b, gap: bytes) -> None:
    if not gap:
        return
    meaningful = gap.translate(None, _LAYOUT_BYTES)
    if meaningful:
        digest.update(_SEPARATOR)
        digest.update(meaningful)
