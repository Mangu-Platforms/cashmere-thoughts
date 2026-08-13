from __future__ import annotations

import json
from pathlib import Path

from .models import MasteringProfile
from .store import data_dir


def _bundled_profiles() -> Path:
    return Path(__file__).with_name("profiles.json")


def load_profiles() -> dict[str, MasteringProfile]:
    override = data_dir() / "profiles.json"
    path = override if override.exists() else _bundled_profiles()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {name: MasteringProfile.model_validate(data) for name, data in raw.items()}


def install_profile_override() -> Path:
    target = data_dir() / "profiles.json"
    if not target.exists():
        target.write_text(_bundled_profiles().read_text(encoding="utf-8"), encoding="utf-8")
    return target
