from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass

from .registry import load_registry, validate_record
from .store import ensure_layout
from .tts_backend import PiperBackend


@dataclass
class DoctorCheck:
    name: str
    ready: bool
    detail: str


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "missing"


def _ffmpeg_filters() -> tuple[bool, str]:
    if shutil.which("ffmpeg") is None:
        return False, "ffmpeg not on PATH"
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    missing = [
        name
        for name in ("loudnorm", "sidechaincompress")
        if name not in combined
    ]
    if missing:
        return False, f"missing filters: {', '.join(missing)}"
    return True, "loudnorm + sidechaincompress available"


def run_checks() -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []

    for executable in ("ffmpeg", "ffprobe"):
        location = shutil.which(executable)
        checks.append(
            DoctorCheck(
                executable,
                location is not None,
                location or "not on PATH",
            )
        )

    filter_ok, filter_detail = _ffmpeg_filters()
    checks.append(DoctorCheck("ffmpeg-filters", filter_ok, filter_detail))

    piper_ok, piper_detail = PiperBackend.probe()
    checks.append(DoctorCheck("piper", piper_ok, piper_detail))

    try:
        root = ensure_layout()
        probe = root / ".doctor-write-test"
        probe.write_text("ready", encoding="utf-8")
        with probe.open("rb") as handle:
            os.fsync(handle.fileno())
        probe.unlink()
        checks.append(DoctorCheck("dirs", True, str(root)))
    except OSError as exc:
        checks.append(DoctorCheck("dirs", False, str(exc)))

    try:
        registry = load_registry()
        failures: list[str] = []
        for voice_id, record in registry.items():
            try:
                validate_record(voice_id, record)
            except Exception as exc:
                failures.append(f"{voice_id}: {exc}")
        checks.append(
            DoctorCheck(
                "voices",
                not failures,
                "; ".join(failures) or f"{len(registry)} entries",
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck("voices", False, str(exc)))

    ffmpeg_version = "missing"
    if shutil.which("ffmpeg"):
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            check=False,
        )
        ffmpeg_version = (
            result.stdout.splitlines()[0]
            if result.stdout
            else "unknown"
        )

    checks.append(
        DoctorCheck(
            "versions",
            True,
            (
                f"skillvoice={_distribution_version('skillvoice-studio')}; "
                f"piper-tts={_distribution_version('piper-tts')}; "
                f"{ffmpeg_version}"
            ),
        )
    )
    return checks


def checks_json(checks: list[DoctorCheck]) -> str:
    return json.dumps([asdict(check) for check in checks], indent=2)
