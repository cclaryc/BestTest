"""Ask a running analysis service about the bundled example and check the answer.

    python scripts/smoke.py [http://127.0.0.1:8000]

The service must have been started with its snapshot root set to
``examples/discount``, so that the snapshots ``base`` and ``head`` exist. Uses
only the standard library, so it runs anywhere Python does.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "discount"
EXPECTED = {
    "<module>": "modified",
    "clamp": "cosmetic",
    "calculate_discount": "modified",
    "Cart.clear": "added",
}


def wait_until_ready(base_url: str, seconds: float = 30.0) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            with urllib.request.urlopen(f"{base_url}/readyz", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        if time.monotonic() > deadline:
            raise SystemExit(f"service at {base_url} did not become ready in {seconds:.0f} s")
        time.sleep(0.5)


def main() -> int:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    wait_until_ready(base_url)

    body = json.dumps(
        {
            "base": {"commit": "a" * 40, "snapshot": "base"},
            "head": {"commit": "b" * 40, "snapshot": "head"},
            "diff": (EXAMPLE / "change.diff").read_text(encoding="utf-8"),
        }
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/v1/changed-symbols",
        data=body,
        headers={"Content-Type": "application/json", "X-Request-ID": "smoke-test"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
            request_id = response.headers.get("X-Request-ID")
    except urllib.error.HTTPError as error:
        print(f"FAILED: HTTP {error.code}\n{error.read().decode(errors='replace')}")
        return 1

    print(json.dumps(result, indent=2))
    actual = {
        symbol["key"]: symbol["change"]
        for file_change in result["files"]
        for symbol in file_change["symbols"]
    }
    if actual != EXPECTED or not result["complete"] or request_id != "smoke-test":
        print(f"\nFAILED: expected {EXPECTED}, got {actual} (request id {request_id!r})")
        return 1
    print("\nOK: the service returned the expected symbols.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
