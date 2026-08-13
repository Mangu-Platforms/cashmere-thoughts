from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

from .errors import AudioError
from .models import MasteringProfile


def run_command(args: list[str], *, stage: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise AudioError(
            f"Required executable missing: {args[0]}",
            remedy="Install the pinned ffmpeg/ffprobe build and open a new shell.",
            stage=stage,
        ) from exc
    if result.returncode != 0:
        raise AudioError(
            result.stderr.strip() or f"{args[0]} exited {result.returncode}",
            remedy="Inspect the named stage input with ffprobe, correct the issue, then resume.",
            stage=stage,
        )
    return result


def probe_audio(path: Path) -> dict[str, int | float | str]:
    result = run_command([
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels:format=duration",
        "-of", "json",
        str(path),
    ], stage="preflight")
    payload = json.loads(result.stdout)
    stream = payload["streams"][0]
    return {
        "codec": stream["codec_name"],
        "sample_rate": int(stream["sample_rate"]),
        "channels": int(stream["channels"]),
        "duration": float(payload["format"]["duration"]),
    }


def normalize_chunk(
    input_path: Path,
    output_path: Path,
    *,
    native_sample_rate: int,
) -> None:
    if native_sample_rate == 24000:
        shutil.copy2(input_path, output_path)
        return
    run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path),
        "-ar", "24000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(output_path),
    ], stage="generating_voice")


def _concat_escape(path: Path) -> str:
    return str(path.resolve()).replace("'", r"'\''")


def write_concat_list(paths: list[Path], list_path: Path) -> None:
    list_path.write_text(
        "".join(f"file '{_concat_escape(path)}'\n" for path in paths),
        encoding="utf-8",
    )


def concat_wav(paths: list[Path], output_path: Path) -> None:
    if not paths:
        raise AudioError(
            "No audio chunks available for assembly.",
            remedy="Verify the manuscript produced at least one non-empty chunk.",
            stage="generating_voice",
        )
    list_path = output_path.with_suffix(".concat.txt")
    write_concat_list(paths, list_path)
    run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        str(output_path),
    ], stage="generating_voice")


def _atempo_chain(value: float) -> list[float]:
    factors: list[float] = []
    while value < 0.5:
        factors.append(0.5)
        value /= 0.5
    while value > 2.0:
        factors.append(2.0)
        value /= 2.0
    factors.append(value)
    return factors


def apply_attributes(
    input_path: Path,
    output_path: Path,
    *,
    pitch_semitones: float,
    volume: float,
) -> None:
    filters: list[str] = []
    if abs(pitch_semitones) > 1e-9:
        ratio = 2.0 ** (pitch_semitones / 12.0)
        filters.extend([
            f"asetrate=24000*{ratio:.12f}",
            "aresample=24000",
        ])
        filters.extend(
            f"atempo={factor:.12f}"
            for factor in _atempo_chain(1.0 / ratio)
        )
    if abs(volume - 1.0) > 1e-9:
        filters.append(f"volume={volume:.8f}")

    if not filters:
        shutil.copy2(input_path, output_path)
        return

    run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path),
        "-af", ",".join(filters),
        "-ar", "24000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(output_path),
    ], stage="generating_voice")


def mix_background(
    voice_path: Path,
    background_path: Path,
    output_path: Path,
    *,
    background_volume: float,
    duck: bool,
) -> None:
    if not background_path.is_file():
        raise AudioError(
            f"Background file missing: {background_path}",
            remedy="Correct the background path from the title sheet and resume.",
            stage="mixing",
        )

    if duck:
        filter_graph = (
            f"[1:a]volume={background_volume}[bed];"
            "[bed][0:a]sidechaincompress="
            "threshold=0.03:ratio=10:attack=20:release=300[ducked];"
            "[0:a][ducked]amix=inputs=2:duration=first:normalize=0[out]"
        )
    else:
        filter_graph = (
            f"[1:a]volume={background_volume}[bed];"
            "[0:a][bed]amix=inputs=2:duration=first:normalize=0[out]"
        )

    run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(voice_path),
        "-stream_loop", "-1",
        "-i", str(background_path),
        "-filter_complex", filter_graph,
        "-map", "[out]",
        "-ar", "24000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(output_path),
    ], stage="mixing")


def loudnorm_analysis(
    input_path: Path,
    profile: MasteringProfile,
) -> dict[str, str]:
    result = run_command([
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", str(input_path),
        "-af",
        (
            f"loudnorm=I={profile.loudness_lufs}:"
            f"TP={profile.true_peak_dbtp}:"
            f"LRA={profile.lra}:print_format=json"
        ),
        "-f", "null", "-",
    ], stage="mastering")
    start = result.stderr.rfind("{")
    end = result.stderr.rfind("}")
    if start < 0 or end < start:
        raise AudioError(
            "loudnorm analysis returned no JSON.",
            remedy="Run ffprobe on the dry WAV and escalate with full ffmpeg stderr if valid.",
            stage="mastering",
        )
    return json.loads(result.stderr[start:end + 1])


def _finite_measurements(analysis: dict[str, str]) -> bool:
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        try:
            if not math.isfinite(float(analysis[key])):
                return False
        except (KeyError, TypeError, ValueError):
            return False
    return True


def master(
    input_path: Path,
    output_path: Path,
    profile: MasteringProfile,
) -> None:
    analysis = loudnorm_analysis(input_path, profile)
    if _finite_measurements(analysis):
        loudnorm = (
            f"loudnorm=I={profile.loudness_lufs}:"
            f"TP={profile.true_peak_dbtp}:"
            f"LRA={profile.lra}:"
            f"measured_I={analysis['input_i']}:"
            f"measured_TP={analysis['input_tp']}:"
            f"measured_LRA={analysis['input_lra']}:"
            f"measured_thresh={analysis['input_thresh']}:"
            f"offset={analysis['target_offset']}:"
            "linear=true:print_format=summary"
        )
    else:
        loudnorm = (
            f"loudnorm=I={profile.loudness_lufs}:"
            f"TP={profile.true_peak_dbtp}:"
            f"LRA={profile.lra}:linear=false:print_format=summary"
        )

    run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path),
        "-af", loudnorm,
        "-ar", str(profile.delivery_sample_rate),
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(output_path),
    ], stage="mastering")


def export_audio(
    input_path: Path,
    output_path: Path,
    *,
    output_format: str,
    profile: MasteringProfile,
    title: str | None = None,
    author: str | None = None,
) -> None:
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path),
    ]
    if title:
        args.extend(["-metadata", f"title={title}"])
    if author:
        args.extend(["-metadata", f"artist={author}"])
    args.extend(["-metadata", "comment=Generated by SkillVoice Studio"])

    if output_format == "wav":
        args.extend(["-c:a", "pcm_s16le", str(output_path)])
    elif output_format == "mp3":
        args.extend([
            "-c:a", "libmp3lame",
            "-b:a", profile.bitrate or "192k",
            str(output_path),
        ])
    elif output_format == "m4b":
        args.extend([
            "-c:a", "aac",
            "-b:a", profile.bitrate or "128k",
            "-f", "ipod",
            str(output_path),
        ])
    else:
        raise AudioError(
            f"Unsupported output format: {output_format}",
            remedy="Use wav, mp3, or m4b.",
            stage="exporting",
        )
    run_command(args, stage="exporting")


def probe_duration(path: Path) -> float:
    result = run_command([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(path),
    ], stage="exporting")
    return float(result.stdout.strip())


def write_ffmetadata(
    path: Path,
    *,
    title: str,
    author: str,
    chapters: list[tuple[str, int, int]],
) -> None:
    def escape(value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace("=", "\\=")
            .replace(";", "\\;")
            .replace("#", "\\#")
        )

    lines = [";FFMETADATA1", f"title={escape(title)}", f"artist={escape(author)}"]
    for chapter_title, start_ms, end_ms in chapters:
        lines.extend([
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start_ms}",
            f"END={end_ms}",
            f"title={escape(chapter_title)}",
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mux_chaptered_m4b(
    audio_path: Path,
    metadata_path: Path,
    output_path: Path,
    *,
    bitrate: str = "128k",
) -> None:
    run_command([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(audio_path),
        "-i", str(metadata_path),
        "-map_metadata", "1",
        "-map_chapters", "1",
        "-c:a", "aac",
        "-b:a", bitrate,
        "-f", "ipod",
        str(output_path),
    ], stage="exporting")
