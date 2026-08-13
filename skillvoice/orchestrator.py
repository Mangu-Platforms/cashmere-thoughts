from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .audio_utils import (
    apply_attributes,
    concat_wav,
    export_audio,
    master,
    mix_background,
    normalize_chunk,
)
from .config import load_profiles
from .errors import SkillVoiceError
from .models import (
    ChunkManifest,
    GenerationJob,
    JobStatus,
    ManifestChunk,
)
from .registry import require_active_voice
from .skills import load_skill
from .store import data_dir, read_model, write_model
from .tts_backend import PiperBackend, TTSBackend

LOGGER = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text: str, *, max_chars: int = 900) -> list[str]:
    paragraphs = [
        paragraph.strip()
        for paragraph in text.replace("\r\n", "\n").split("\n\n")
        if paragraph.strip()
    ]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        sentences = (
            paragraph.replace(". ", ".|")
            .replace("! ", "!|")
            .replace("? ", "?|")
            .split("|")
        )
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            candidate = f"{current} {sentence}".strip()
            if len(candidate) <= max_chars:
                current = candidate
                continue

            if current:
                chunks.append(current)
            while len(sentence) > max_chars:
                split_at = sentence.rfind(" ", 0, max_chars)
                if split_at < max_chars // 2:
                    split_at = max_chars
                chunks.append(sentence[:split_at].strip())
                sentence = sentence[split_at:].strip()
            current = sentence

    if current:
        chunks.append(current)

    if not chunks:
        raise SkillVoiceError(
            "Manuscript contains no speakable text.",
            remedy="Provide a non-empty UTF-8 plain-text manuscript.",
        )
    return chunks


def job_path(job_id: str) -> Path:
    return data_dir() / "jobs" / f"{job_id}.json"


def load_job(job_id: str) -> GenerationJob:
    return read_model(job_path(job_id), GenerationJob)


def _update(
    job: GenerationJob,
    *,
    status: JobStatus,
    error: str | None = None,
    remedy: str | None = None,
    stage: str | None = None,
) -> None:
    job.status = status
    job.error = error
    job.remedy = remedy
    job.stage = stage
    job.updated = _now()
    write_model(job_path(job.job_id), job)


def _manifest_for(chunks: list[str], text_sha256: str) -> ChunkManifest:
    return ChunkManifest(
        text_sha256=text_sha256,
        chunks=[
            ManifestChunk(
                i=index,
                sha=_sha(chunk),
                path=f"chunk_{index:04d}.wav",
                done=False,
            )
            for index, chunk in enumerate(chunks)
        ],
    )


def _load_or_reset_manifest(
    *,
    path: Path,
    chunks: list[str],
    text_sha256: str,
) -> tuple[ChunkManifest, bool]:
    if not path.exists():
        manifest = _manifest_for(chunks, text_sha256)
        write_model(path, manifest)
        return manifest, False

    manifest = read_model(path, ChunkManifest)
    if manifest.text_sha256 != text_sha256:
        LOGGER.warning("source text hash changed; invalidating all cached chunks")
        manifest = _manifest_for(chunks, text_sha256)
        write_model(path, manifest)
        return manifest, True

    if len(manifest.chunks) != len(chunks):
        LOGGER.warning("chunk layout changed; invalidating all cached chunks")
        manifest = _manifest_for(chunks, text_sha256)
        write_model(path, manifest)
        return manifest, True

    for entry, chunk in zip(manifest.chunks, chunks, strict=True):
        if entry.sha != _sha(chunk):
            LOGGER.warning("chunk hash changed; invalidating all cached chunks")
            manifest = _manifest_for(chunks, text_sha256)
            write_model(path, manifest)
            return manifest, True
    return manifest, False


def generate(
    *,
    skill_name: str,
    text_file: Path,
    output_format: str | None = None,
    profile_name: str | None = None,
    resume_job_id: str | None = None,
    background: Path | None = None,
    background_volume: float = 0.2,
    duck: bool = False,
    title: str | None = None,
    author: str | None = None,
    backend: TTSBackend | None = None,
) -> GenerationJob:
    skill = load_skill(skill_name)
    voice = require_active_voice(skill.voice_id)
    profiles = load_profiles()
    selected_profile = profile_name or skill.default_profile
    if selected_profile not in profiles:
        raise SkillVoiceError(
            f"Unknown mastering profile: {selected_profile}",
            remedy="Run `skillvoice profile list` and choose a configured profile.",
        )
    profile = profiles[selected_profile]
    selected_format = (output_format or profile.default_format).lower()
    if selected_format not in {"wav", "mp3", "m4b"}:
        raise SkillVoiceError(
            f"Unsupported output format: {selected_format}",
            remedy="Use wav, mp3, or m4b.",
        )

    source = text_file.expanduser().resolve()
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SkillVoiceError(
            f"Cannot read UTF-8 manuscript: {source}",
            remedy="Provide an existing UTF-8 plain-text file.",
        ) from exc

    text_sha256 = _sha(text)
    chunks = chunk_text(text)

    if resume_job_id:
        job = load_job(resume_job_id)
        if job.skill != skill_name:
            raise SkillVoiceError(
                f"Resume job skill mismatch: {job.skill} != {skill_name}",
                remedy=f"Resume with `--skill {job.skill}` or start a new job.",
                job_id=job.job_id,
            )
        work_dir = job.work_dir
        work_dir.mkdir(parents=True, exist_ok=True)
        job.source_path = source
        job.text_sha256 = text_sha256
        job.profile = selected_profile
        job.output_format = selected_format
    else:
        job_id = uuid.uuid4().hex[:12]
        work_dir = data_dir() / "tmp" / job_id
        work_dir.mkdir(parents=True, exist_ok=False)
        job = GenerationJob(
            job_id=job_id,
            skill=skill_name,
            source_path=source,
            text_sha256=text_sha256,
            work_dir=work_dir,
            profile=selected_profile,
            output_format=selected_format,
            updated=_now(),
        )
        write_model(job_path(job.job_id), job)

    manifest_path = work_dir / "manifest.json"
    manifest, invalidated = _load_or_reset_manifest(
        path=manifest_path,
        chunks=chunks,
        text_sha256=text_sha256,
    )
    if invalidated:
        for path in work_dir.glob("chunk_*.wav"):
            path.unlink(missing_ok=True)

    reusable = sum(
        1
        for entry in manifest.chunks
        if (
            entry.done
            and (work_dir / entry.path).is_file()
            and (work_dir / entry.path).stat().st_size > 44
        )
    )
    if resume_job_id:
        LOGGER.info(
            "resuming: %s of %s chunks reused",
            reusable,
            len(manifest.chunks),
        )

    backend = backend or PiperBackend()

    try:
        _update(
            job,
            status=JobStatus.GENERATING_VOICE,
            stage=JobStatus.GENERATING_VOICE.value,
        )
        for entry, chunk in zip(manifest.chunks, chunks, strict=True):
            normalized = work_dir / entry.path
            if entry.done and normalized.is_file() and normalized.stat().st_size > 44:
                continue

            native = work_dir / f"chunk_{entry.i:04d}.native.wav"
            backend.synthesize(
                skill.voice_id,
                chunk,
                skill.attributes,
                native,
            )
            normalize_chunk(
                native,
                normalized,
                native_sample_rate=voice.sample_rate,
            )
            native.unlink(missing_ok=True)
            entry.done = True
            write_model(manifest_path, manifest)

        raw = work_dir / "raw.wav"
        concat_wav(
            [work_dir / entry.path for entry in manifest.chunks],
            raw,
        )

        dry = work_dir / "dry.wav"
        apply_attributes(
            raw,
            dry,
            pitch_semitones=skill.attributes.pitch,
            volume=skill.attributes.volume,
        )

        current = dry
        if background is not None:
            _update(
                job,
                status=JobStatus.MIXING,
                stage=JobStatus.MIXING.value,
            )
            mixed = work_dir / "mixed.wav"
            mix_background(
                dry,
                background.expanduser().resolve(),
                mixed,
                background_volume=background_volume,
                duck=duck,
            )
            current = mixed

        _update(
            job,
            status=JobStatus.MASTERING,
            stage=JobStatus.MASTERING.value,
        )
        mastered = work_dir / "mastered.wav"
        master(current, mastered, profile)

        _update(
            job,
            status=JobStatus.EXPORTING,
            stage=JobStatus.EXPORTING.value,
        )
        output_dir = data_dir() / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{source.stem}-{job.job_id}.{selected_format}"
        export_audio(
            mastered,
            output_path,
            output_format=selected_format,
            profile=profile,
            title=title,
            author=author,
        )

        job.output_path = output_path
        _update(job, status=JobStatus.COMPLETE)
        return job
    except SkillVoiceError as exc:
        exc.job_id = job.job_id
        _update(
            job,
            status=JobStatus.ERROR,
            error=str(exc),
            remedy=exc.remedy,
            stage=exc.stage,
        )
        raise
    except Exception as exc:
        wrapped = SkillVoiceError(
            str(exc),
            remedy="Inspect the job record and run `skillvoice doctor --json` before retrying.",
            stage=job.stage or "unknown",
            job_id=job.job_id,
        )
        _update(
            job,
            status=JobStatus.ERROR,
            error=str(wrapped),
            remedy=wrapped.remedy,
            stage=wrapped.stage,
        )
        raise wrapped from exc
