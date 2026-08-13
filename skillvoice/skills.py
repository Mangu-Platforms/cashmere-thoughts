from __future__ import annotations

from pathlib import Path

from .errors import ConfigError, SkillVoiceError
from .models import Skill, VoiceAttributes
from .registry import require_active_voice
from .store import data_dir, ensure_layout, read_model, write_model


def _skill_path(name: str) -> Path:
    return data_dir() / "skills" / f"{name}.json"


def create_skill(
    *,
    name: str,
    voice_id: str,
    attributes: VoiceAttributes | None = None,
    default_profile: str = "house",
    style_instructions: str = "",
) -> Skill:
    ensure_layout()
    require_active_voice(voice_id)
    path = _skill_path(name)
    if path.exists():
        raise ConfigError(
            f"Skill already exists: {name}",
            remedy=f"Use `skillvoice skill update {name}` or choose a different name.",
            stage="preflight",
        )
    skill = Skill(
        name=name,
        voice_id=voice_id,
        attributes=attributes or VoiceAttributes(),
        default_profile=default_profile,
        style_instructions=style_instructions,
        version=1,
    )
    write_model(path, skill)
    return skill


def load_skill(name: str) -> Skill:
    return read_model(_skill_path(name), Skill)


def list_skills() -> list[Skill]:
    ensure_layout()
    skills_dir = data_dir() / "skills"
    result: list[Skill] = []
    for path in sorted(skills_dir.glob("*.json")):
        try:
            result.append(read_model(path, Skill))
        except Exception:
            continue
    return result


def update_skill(
    name: str,
    *,
    voice_id: str | None = None,
    pace: float | None = None,
    energy: str | None = None,
    pitch: float | None = None,
    volume: float | None = None,
    default_profile: str | None = None,
    style_instructions: str | None = None,
) -> Skill:
    skill = load_skill(name)
    if voice_id is not None:
        require_active_voice(voice_id)
        skill.voice_id = voice_id
    attrs = skill.attributes.model_copy()
    if pace is not None:
        attrs.pace = pace
    if energy is not None:
        from .models import Energy

        attrs.energy = Energy(energy)
    if pitch is not None:
        attrs.pitch = pitch
    if volume is not None:
        attrs.volume = volume
    skill.attributes = attrs
    if default_profile is not None:
        skill.default_profile = default_profile
    if style_instructions is not None:
        skill.style_instructions = style_instructions
    skill.version += 1
    write_model(_skill_path(name), skill)
    return skill
