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
    # After the first account exists, more can sign up only if this is true.
    allow_signup: bool = False
    rules_file: Path | None = None
    # Where trained models are saved and loaded (created by `moneyos ml`).
    models_dir: Path = Path("data/models")
    # The built web app, served at "/" when present (`npm run build` in frontend/).
    frontend_dist: Path = Path("frontend/dist")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **overrides) -> Settings:
        env = os.environ if env is None else env
        mode = DataMode(overrides.pop("data_mode", None) or env.get("MONEYOS_DATA_MODE") or "real")
        rules = env.get("MONEYOS_RULES_FILE")
        models = env.get("MONEYOS_MODELS_DIR")
        values = {
            "data_mode": mode,
            "database_url": env.get("MONEYOS_DATABASE_URL") or DEFAULT_DATABASE_URLS[mode],
            "allow_signup": (env.get("MONEYOS_ALLOW_SIGNUP") or "").lower() in ("1", "true", "yes"),
            "rules_file": Path(rules) if rules else None,
            "models_dir": Path(models) if models else Path("data/models"),
            "frontend_dist": Path(env.get("MONEYOS_FRONTEND_DIST") or "frontend/dist"),
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)
