"""Write or check the committed OpenAPI document.

    python -m analysis.api.openapi            # rewrite openapi.json
    python -m analysis.api.openapi --check    # fail if it is out of date

The document is generated from the Pydantic models, then checked in. Keeping a
copy in the repository means a change to the contract shows up in code review as
a diff of ``openapi.json``, and other services can build against that file
without running this one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from analysis.api.app import create_app
from analysis.api.settings import Settings

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "openapi.json"


def generate() -> dict[str, Any]:
    # The document does not depend on any setting, so a placeholder root is fine.
    return create_app(Settings(snapshot_root=Path("."))).openapi()


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write or check the OpenAPI document.")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--check", action="store_true", help="do not write; exit 1 if stale")
    arguments = parser.parse_args(argv)

    document = generate()
    if arguments.check:
        current = json.loads(arguments.path.read_text(encoding="utf-8"))
        if current != document:
            print(f"{arguments.path} is out of date; run: python -m analysis.api.openapi")
            return 1
        return 0
    arguments.path.write_text(render(document), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
