from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from .audio_utils import (
    concat_wav,
    export_audio,
    mux_chaptered_m4b,
    probe_duration,
    write_ffmetadata,
)
from .config import load_profiles
from .errors import ConfigError, SkillVoiceError
from .models import BookManifest
from .orchestrator import generate
from .store import data_dir

LOGGER = logging.getLogger(__name__)


def init_manifest(path: Path) -> None:
    payload = {
        "title": "Untitled",
        "author": "",
        "skill": "",
        "chapters": [
            {"file": "ch01.txt", "title": "Chapter One"},
            {"file": "ch02.txt", "title": "Chapter Two"},
        ],
        "profile": "house",
        "output_format": "m4b",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> BookManifest:
    if not path.exists():
        raise ConfigError(
            f"Book manifest not found: {path}",
            remedy="Run `skillvoice book init` or provide a valid book.json.",
            stage="preflight",
        )
    return BookManifest.model_validate_json(path.read_text(encoding="utf-8"))


def generate_book(path: Path, *, split: bool = False) -> tuple[Path, list[Path]]:
    manifest = load_manifest(path)
    if not manifest.skill:
        raise ConfigError(
            "Book manifest missing skill",
            remedy="Set the skill field in book.json",
            stage="preflight",
        )
    profiles = load_profiles()
    if manifest.profile not in profiles:
        raise ConfigError(
            f"Unknown profile: {manifest.profile}",
            remedy="Run `skillvoice profile list`",
            stage="preflight",
        )

    chapter_outputs: list[Path] = []
    work = data_dir() / "work" / f"book-{path.stem}"
    work.mkdir(parents=True, exist_ok=True)

    for idx, chapter in enumerate(manifest.chapters):
        chapter_path = path.parent / chapter.file
        if not chapter_path.exists():
            raise ConfigError(
                f"Chapter file missing: {chapter_path}",
                remedy="Ensure all chapter files listed in the manifest exist.",
                stage="preflight",
            )
        job = generate(
            skill_name=manifest.skill,
            text_file=chapter_path,
            output_format="wav",
            profile_name=manifest.profile,
            title=chapter.title,
            author=manifest.author,
        )
        if job.output_path is None:
            raise SkillVoiceError(
                f"Chapter {idx} produced no output",
                remedy="Inspect the job log and re-run.",
                stage="exporting",
            )
        dest = work / f"chapter_{idx:03d}.wav"
        shutil.copy2(job.output_path, dest)
        chapter_outputs.append(dest)

    if not chapter_outputs:
        raise SkillVoiceError(
            "No chapters rendered",
            remedy="Add chapters to the manifest.",
            stage="preflight",
        )

    durations = [probe_duration(p) for p in chapter_outputs]
    meta_path = work / "ffmetadata.txt"
    write_ffmetadata(
        meta_path,
        title=manifest.title,
        author=manifest.author,
        chapters=[(c.title, d) for c, d in zip(manifest.chapters, durations)],
    )

    joined = work / "joined.wav"
    concat_wav(chapter_outputs, joined)

    out_name = manifest.output or path.with_suffix(f".{manifest.output_format}")
    if isinstance(out_name, str):
        out_name = Path(out_name)
    if not out_name.is_absolute():
        out_name = path.parent / out_name

    if manifest.output_format == "m4b":
        mux_chaptered_m4b(joined, meta_path, out_name)
    else:
        export_audio(joined, out_name, format=manifest.output_format)

    split_paths: list[Path] = []
    if split:
        for idx, src in enumerate(chapter_outputs):
            dest = path.parent / f"{path.stem}_ch{idx+1:02d}.wav"
            shutil.copy2(src, dest)
            split_paths.append(dest)

    return out_name, split_paths
