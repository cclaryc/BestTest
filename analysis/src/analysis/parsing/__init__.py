from analysis.parsing.adapter import AdapterRegistry, LanguageAdapter, ParsedSource
from analysis.parsing.python import PythonAdapter


def default_registry() -> AdapterRegistry:
    """The languages BestTest understands today."""
    return AdapterRegistry((PythonAdapter(),))


__all__ = [
    "AdapterRegistry",
    "LanguageAdapter",
    "ParsedSource",
    "PythonAdapter",
    "default_registry",
]
