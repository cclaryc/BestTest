"""Service configuration, read once from environment variables at start-up."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PREFIX = "BESTTEST_"


class SettingsError(ValueError):
    """The environment does not describe a usable configuration."""


@dataclass(frozen=True, slots=True)
class Settings:
    snapshot_root: Path
    """Directory whose sub-directories are repository snapshots, one per id."""
    max_request_bytes: int = 8 * 1024 * 1024
    max_file_bytes: int = 1_000_000
    max_files: int = 1_000
    time_budget_seconds: float = 30.0
    host: str = "127.0.0.1"
    """Loopback by default: the service has no authentication of its own."""
    port: int = 8000

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        root = env.get(f"{PREFIX}SNAPSHOT_ROOT", "").strip()
        if not root:
            raise SettingsError(f"{PREFIX}SNAPSHOT_ROOT must be set to the snapshot directory")

        defaults = cls(snapshot_root=Path(root))
        return cls(
            snapshot_root=Path(root),
            max_request_bytes=_positive(env, "MAX_REQUEST_BYTES", defaults.max_request_bytes, int),
            max_file_bytes=_positive(env, "MAX_FILE_BYTES", defaults.max_file_bytes, int),
            max_files=_positive(env, "MAX_FILES", defaults.max_files, int),
            time_budget_seconds=_positive(
                env, "TIME_BUDGET_SECONDS", defaults.time_budget_seconds, float
            ),
            host=env.get(f"{PREFIX}HOST", "").strip() or defaults.host,
            port=_positive(env, "PORT", defaults.port, int),
        )


def _positive[Number: (int, float)](
    env: Mapping[str, str], name: str, default: Number, convert: type[Number]
) -> Number:
    raw = env.get(f"{PREFIX}{name}", "").strip()
    if not raw:
        return default
    try:
        value = convert(raw)
    except ValueError:
        raise SettingsError(f"{PREFIX}{name} must be a number, got {raw!r}") from None
    if not value > 0:
        raise SettingsError(f"{PREFIX}{name} must be greater than zero, got {raw!r}")
    return value
