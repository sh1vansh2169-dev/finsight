"""Settings read from environment variables. See .env.example for the list."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class DataMode(StrEnum):
    REAL = "real"
    SAMPLE = "sample"


# Relative to the directory the server is started from (the repo root in
# the documented workflow). Real and sample data never share a file.
DEFAULT_DATABASE_URLS = {
    DataMode.REAL: "sqlite:///data/moneyos.db",
    DataMode.SAMPLE: "sqlite:///data/sample/moneyos-sample.db",
}


@dataclass(frozen=True, slots=True)
class Settings:
    data_mode: DataMode = DataMode.REAL
    database_url: str = DEFAULT_DATABASE_URLS[DataMode.REAL]
    # When set, every /api/v1 request needs "Authorization: Bearer <token>".
    api_token: str | None = None
    rules_file: Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **overrides) -> Settings:
        env = os.environ if env is None else env
        mode = DataMode(overrides.pop("data_mode", None) or env.get("MONEYOS_DATA_MODE") or "real")
        rules = env.get("MONEYOS_RULES_FILE")
        values = {
            "data_mode": mode,
            "database_url": env.get("MONEYOS_DATABASE_URL") or DEFAULT_DATABASE_URLS[mode],
            "api_token": env.get("MONEYOS_API_TOKEN") or None,
            "rules_file": Path(rules) if rules else None,
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)
