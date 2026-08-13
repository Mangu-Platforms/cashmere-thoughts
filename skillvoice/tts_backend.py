from __future__ import annotations

import concurrent.futures
import inspect
import math
import os
import wave
from abc import ABC, abstractmethod
from pathlib import Path

from .errors import SynthesisError
from .models import Energy, VoiceAttributes
from .registry import require_active_voice


class TTSBackend(ABC):
    @abstractmethod
    def synthesize(
        self,
        voice_id: str,
        text: str,
        attributes: VoiceAttributes,
        output_path: Path,
    ) -> None:
        """Write a mono PCM WAV and raise SynthesisError on failure."""


class PiperBackend(TTSBackend):
    """Pinned Piper 1.6 in-process backend."""

    def __init__(self) -> None:
        try:
            from piper import PiperVoice, SynthesisConfig
        except ImportError as exc:
            raise SynthesisError(
                "Piper import failed.",
                remedy="Install/pin piper-tts exactly as specified in doc 08.",
                stage="generating_voice",
            ) from exc

        parameters = inspect.signature(SynthesisConfig).parameters
        required = {"length_scale", "noise_scale", "noise_w_scale"}
        missing = required - set(parameters)
        if missing:
            raise SynthesisError(
                f"Piper SynthesisConfig contract mismatch: missing {sorted(missing)}",
                remedy="Pin piper-tts per doc 08.",
                stage="generating_voice",
            )

        self._PiperVoice = PiperVoice
        self._SynthesisConfig = SynthesisConfig
        self._cache: dict[str, object] = {}

    @classmethod
    def probe(cls) -> tuple[bool, str]:
        try:
            from piper import PiperVoice, SynthesisConfig

            parameters = set(inspect.signature(SynthesisConfig).parameters)
            required = {"length_scale", "noise_scale", "noise_w_scale"}
            if not required.issubset(parameters):
                return False, f"SynthesisConfig missing {sorted(required - parameters)}"
            return True, "ready"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def _load(self, model_path: Path):
        key = str(model_path)
        if key not in self._cache:
            self._cache[key] = self._PiperVoice.load(str(model_path))
        return self._cache[key]

    def synthesize(
        self,
        voice_id: str,
        text: str,
        attributes: VoiceAttributes,
        output_path: Path,
    ) -> None:
        record = require_active_voice(voice_id)
        voice = self._load(record.model)

        length_scale = 1.0 / attributes.pace
        cfg_kwargs: dict = {"length_scale": length_scale}
        if attributes.energy == Energy.LOW:
            cfg_kwargs.update({"noise_scale": 0.4, "noise_w_scale": 0.6})
        elif attributes.energy == Energy.HIGH:
            cfg_kwargs.update({"noise_scale": 0.8, "noise_w_scale": 0.8})

        cfg = self._SynthesisConfig(**cfg_kwargs)
        part = output_path.with_suffix(".part")

        def _run() -> None:
            with wave.open(str(part), "wb") as wav:
                voice.synthesize_wav(text, wav, syn_config=cfg)

        timeout = max(120, len(text) // 20)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            try:
                future.result(timeout=timeout)
            except concurrent.futures.TimeoutError as exc:
                raise SynthesisError(
                    f"Piper synthesis timed out after {timeout}s",
                    remedy="Reduce chunk size or check model health.",
                    stage="generating_voice",
                ) from exc
            except Exception as exc:
                raise SynthesisError(
                    f"Piper synthesis failed: {exc}",
                    remedy="Check voice model and Piper installation.",
                    stage="generating_voice",
                ) from exc

        if not part.exists() or part.stat().st_size == 0:
            raise SynthesisError(
                "Piper produced empty output",
                remedy="Check model and text input.",
                stage="generating_voice",
            )
        part.replace(output_path)


class MockBackend(TTSBackend):
    """Deterministic mock that emits 22 050 Hz mono so resample path is exercised."""

    def synthesize(
        self,
        voice_id: str,
        text: str,
        attributes: VoiceAttributes,
        output_path: Path,
    ) -> None:
        import struct

        sample_rate = 22050
        duration = max(0.3, min(8.0, len(text) * 0.04 / attributes.pace))
        n_samples = int(sample_rate * duration)
        amplitude = 0.2 * attributes.volume
        part = output_path.with_suffix(".part")
        with wave.open(str(part), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for i in range(n_samples):
                t = i / sample_rate
                value = int(32767 * amplitude * math.sin(2 * math.pi * 220 * t))
                wav.writeframes(struct.pack("<h", value))
        part.replace(output_path)
