"""Load organization-neutral configuration."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "default.toml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or default_config_path()
    with cfg_path.open("rb") as fh:
        return tomllib.load(fh)
