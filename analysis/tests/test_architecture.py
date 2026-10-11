"""Keep the packages layered: lower layers must not import higher ones."""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "src" / "analysis"

# Each area may import only the areas listed for it.
ALLOWED = {
    "model": set(),
    "sources": set(),
    "diff": {"model"},
    "parsing": {"model"},
    "symbols": {"model", "diff", "parsing", "sources"},
    "cli": {"model", "diff", "parsing", "sources", "symbols"},
    # The two front ends are siblings: neither may reach into the other.
    "api": {"model", "diff", "parsing", "sources", "symbols"},
}


def area_of(path: Path) -> str:
    return path.relative_to(SOURCE).parts[0].removesuffix(".py")


def imported_areas(path: Path) -> set[str]:
    areas: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        for name in names:
            parts = name.split(".")
            if parts[0] == "analysis" and len(parts) > 1:
                areas.add(parts[1])
    return areas


def test_packages_only_import_downwards():
    violations = []
    for path in sorted(SOURCE.rglob("*.py")):
        area = area_of(path)
        if area not in ALLOWED:
            continue  # __init__ and __main__ sit above everything
        extra = imported_areas(path) - ALLOWED[area] - {area}
        if extra:
            violations.append(f"{path.relative_to(SOURCE)} imports {sorted(extra)}")

    assert violations == []
