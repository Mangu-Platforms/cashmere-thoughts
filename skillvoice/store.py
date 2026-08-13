from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .errors import ConfigError

T = TypeVar("T", bound=BaseModel)


def data_dir() -> Path:
    root = Path(os.environ.get("SKILLVOICE_DATA_DIR", Path.home() / ".skillvoice"))
    return root


def ensure_layout() -> Path:
    root = data_dir()
    for sub in ("voices", "skills", "jobs", "work", "profiles"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def write_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    with tmp.open("rb") as handle:
        os.fsync(handle.fileno())
    tmp.replace(path)


def read_model(path: Path, model_cls: type[T]) -> T:
    if not path.exists():
        raise ConfigError(
            f"Missing state file: {path}",
            remedy="Run the corresponding create/init command first.",
            stage="preflight",
        )
    return model_cls.model_validate_json(path.read_text(encoding="utf-8"))
