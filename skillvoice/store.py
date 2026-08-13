from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .errors import ConfigError

ModelT = TypeVar("ModelT", bound=BaseModel)


def data_dir() -> Path:
    root = Path(os.environ.get("SKILLVOICE_DATA_DIR", Path.home() / ".skillvoice"))
    return root


def ensure_layout() -> Path:
    root = data_dir()
    for sub in ("voices", "skills", "jobs", "work", "profiles"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    with tmp.open("rb") as handle:
        os.fsync(handle.fileno())
    tmp.replace(path)


def write_model(path: Path, model: BaseModel) -> None:
    atomic_write_text(path, model.model_dump_json(indent=2))


def read_model(path: Path, model_type: type[ModelT]) -> ModelT:
    if not path.exists():
        raise ConfigError(
            f"Missing state file: {path}",
            remedy="Run the corresponding create/init command first.",
            stage="preflight",
        )
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))
