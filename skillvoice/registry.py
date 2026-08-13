from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import ValidationError

from .errors import ConfigError
from .models import VoiceRecord, VoiceStatus
from .store import atomic_write_text, data_dir


def registry_path() -> Path:
    return data_dir() / "voices.json"


def _serialize(records: dict[str, VoiceRecord]) -> str:
    payload = {
        voice_id: {
            **record.model_dump(mode="json"),
            "model": str(record.model),
            "config": str(record.config),
        }
        for voice_id, record in records.items()
    }
    return json.dumps(payload, indent=2) + "\n"


def load_registry() -> dict[str, VoiceRecord]:
    path = registry_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, VoiceRecord] = {}
    for voice_id, data in raw.items():
        try:
            result[voice_id] = VoiceRecord.model_validate(data)
        except ValidationError as exc:
            raise ConfigError(
                f"Invalid registry entry for {voice_id}: {exc}",
                remedy="Fix or remove the entry in voices.json",
                stage="preflight",
            ) from exc
    return result


def save_registry(records: dict[str, VoiceRecord]) -> None:
    atomic_write_text(registry_path(), _serialize(records))


def validate_record(voice_id: str, record: VoiceRecord) -> None:
    if not record.model.exists():
        raise ConfigError(
            f"Voice model missing for {voice_id}: {record.model}",
            remedy="Restore the model file or re-run skillvoice voice add",
            stage="preflight",
        )
    if not record.config.exists():
        raise ConfigError(
            f"Voice config missing for {voice_id}: {record.config}",
            remedy="The adjacent .onnx.json is required",
            stage="preflight",
        )
    try:
        cfg = json.loads(record.config.read_text(encoding="utf-8"))
        sr = int(cfg.get("audio", {}).get("sample_rate") or cfg.get("sample_rate") or 0)
    except Exception as exc:
        raise ConfigError(
            f"Cannot read sample_rate for {voice_id}",
            remedy="Ensure the .onnx.json is valid",
            stage="preflight",
        ) from exc
    if sr != record.sample_rate:
        raise ConfigError(
            f"Sample rate drift for {voice_id}: registry={record.sample_rate} file={sr}",
            remedy="Re-add the voice so the registry is revalidated",
            stage="preflight",
        )


def require_active_voice(voice_id: str) -> VoiceRecord:
    records = load_registry()
    if voice_id not in records:
        raise ConfigError(
            f"Unknown voice: {voice_id}",
            remedy="Run skillvoice voice add ...",
            stage="preflight",
        )
    record = records[voice_id]
    if record.status != VoiceStatus.ACTIVE:
        raise ConfigError(
            f"Voice {voice_id} is not active (status={record.status.value})",
            remedy="Only active voices can be used for generation",
            stage="preflight",
        )
    validate_record(voice_id, record)
    return record


def add_voice(
    voice_id: str,
    model: Path,
    *,
    actor: str = "",
    notes: str = "",
    approved_uses: str = "",
    status: VoiceStatus = VoiceStatus.ACTIVE,
) -> VoiceRecord:
    model = model.resolve()
    config = model.with_suffix(model.suffix + ".json")
    if not model.exists():
        raise ConfigError(
            f"Model file not found: {model}",
            remedy="Provide a valid .onnx path",
            stage="preflight",
        )
    if not config.exists():
        raise ConfigError(
            f"Adjacent config required: {config}",
            remedy="Piper models must have a matching .onnx.json",
            stage="preflight",
        )
    try:
        cfg = json.loads(config.read_text(encoding="utf-8"))
        sample_rate = int(
            cfg.get("audio", {}).get("sample_rate") or cfg.get("sample_rate") or 0
        )
    except Exception as exc:
        raise ConfigError(
            f"Cannot parse sample_rate from {config}",
            remedy="Ensure the .onnx.json is valid JSON with sample_rate",
            stage="preflight",
        ) from exc
    if sample_rate <= 0:
        raise ConfigError(
            f"Invalid sample_rate in {config}",
            remedy="sample_rate must be a positive integer",
            stage="preflight",
        )

    records = load_registry()
    record = VoiceRecord(
        engine="piper",
        model=model,
        config=config,
        sample_rate=sample_rate,
        actor=actor,
        notes=notes,
        approved_uses=approved_uses,
        status=status,
    )
    records[voice_id] = record
    save_registry(records)
    return record
