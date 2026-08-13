from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .errors import AudioError, SkillVoiceError
from .models import MasteringProfile


def _ffprobe_loudness(path: Path) -> dict:
    # Simplified probe for QC; full implementation uses loudnorm analysis
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=sample_rate,channels,codec_name",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AudioError(
            f"ffprobe failed on {path}",
            remedy="Ensure the file is a valid audio file and ffprobe is on PATH.",
            stage="qc",
        )
    return json.loads(result.stdout)


def validate_output(path: Path, profile: MasteringProfile) -> dict:
    if not path.exists():
        raise SkillVoiceError(
            f"Output file missing: {path}",
            remedy="Re-run generation.",
            stage="qc",
        )
    info = _ffprobe_loudness(path)
    # Basic structural checks; full LUFS analysis lives in audio_utils/master
    streams = info.get("streams") or []
    if not streams:
        raise AudioError(
            "No audio streams found",
            remedy="Regenerate the file.",
            stage="qc",
        )
    stream = streams[0]
    report = {
        "path": str(path),
        "profile": profile.name,
        "codec": stream.get("codec_name"),
        "sample_rate": stream.get("sample_rate"),
        "channels": stream.get("channels"),
        "duration": info.get("format", {}).get("duration"),
        "status": "pass",
    }
    return report
