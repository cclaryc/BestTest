"""Run the service: ``python -m analysis.api``."""

from __future__ import annotations

import sys

import uvicorn

from analysis.api.app import create_app
from analysis.api.settings import Settings, SettingsError


def main() -> int:
    try:
        settings = Settings.from_env()
    except SettingsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        # The service writes its own request log, as JSON and with request ids.
        access_log=False,
        server_header=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
