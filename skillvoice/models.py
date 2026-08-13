from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Energy(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class VoiceStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    CANDIDATE = "candidate"


class VoiceAttributes(BaseModel):
    pace: float = Field(default=1.0, gt=0.25, le=4.0)
    energy: Energy = Energy.NORMAL
    pitch: float = Field(default=0.0, ge=-24.0, le=24.0)
    volume: float = Field(default=1.0, gt=0.0, le=4.0)


class VoiceRecord(BaseModel):
    engine: Literal["piper"] = "piper"
    model: Path
    config: Path
    sample_rate: int = Field(gt=0)
    actor: str = ""
    notes: str = ""
    approved_uses: str = ""
    status: VoiceStatus = VoiceStatus.ACTIVE


class Skill(BaseModel):
    name: str
    voice_id: str
    attributes: VoiceAttributes = Field(default_factory=VoiceAttributes)
    default_profile: str = "house"
    style_instructions: str = ""
    version: int = Field(default=1, ge=1)


class MasteringProfile(BaseModel):
    name: str
    loudness_lufs: float
    true_peak_dbtp: float
    lra: float
    delivery_sample_rate: int = 44100
    peak_mode: Literal["truepeak"] = "truepeak"
    default_format: Literal["wav", "mp3", "m4b"] = "wav"
    bitrate: str | None = None
    chapters_required: bool = False


class ManifestChunk(BaseModel):
    i: int
    sha: str
    path: str
    done: bool = False


class ChunkManifest(BaseModel):
    text_sha256: str
    chunks: list[ManifestChunk]


class JobStatus(StrEnum):
    PENDING = "pending"
    GENERATING_VOICE = "generating_voice"
    MIXING = "mixing"
    MASTERING = "mastering"
    EXPORTING = "exporting"
    COMPLETE = "complete"
    ERROR = "error"


class GenerationJob(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.PENDING
    skill: str
    source_path: Path
    text_sha256: str
    work_dir: Path
    profile: str
    output_format: str
    output_path: Path | None = None
    updated: str
    error: str | None = None
    remedy: str | None = None
    stage: str | None = None


class BookChapter(BaseModel):
    file: Path
    title: str


class BookManifest(BaseModel):
    title: str
    author: str
    skill: str
    chapters: list[BookChapter]
    profile: str = "house"
    output_format: Literal["m4b", "mp3", "wav"] = "m4b"
    output: Path | None = None
