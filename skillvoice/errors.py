from __future__ import annotations


class SkillVoiceError(RuntimeError):
    """Base operator-facing failure."""

    def __init__(
        self,
        message: str,
        *,
        remedy: str,
        stage: str = "preflight",
        job_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.remedy = remedy
        self.stage = stage
        self.job_id = job_id


class ConfigError(SkillVoiceError):
    """Configuration or state failure."""


class SynthesisError(SkillVoiceError):
    """TTS synthesis failure."""


class AudioError(SkillVoiceError):
    """ffmpeg/ffprobe processing failure."""
