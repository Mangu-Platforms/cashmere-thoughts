from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from . import __version__
from .book import generate_book, init_manifest, load_manifest
from .config import install_profile_override, load_profiles
from .doctor import checks_json, run_checks
from .errors import SkillVoiceError
from .models import Energy, VoiceAttributes, VoiceStatus
from .orchestrator import generate as run_generation
from .orchestrator import load_job
from .qc import validate_output
from .registry import add_voice, load_registry
from .skills import create_skill, list_skills, load_skill, update_skill
from .store import data_dir, ensure_layout

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

app = typer.Typer(
    name="skillvoice",
    help="SkillVoice Studio — local-first house narration pipeline for Piper TTS, "
    "resumable jobs, and chaptered audiobook export.",
    no_args_is_help=True,
    invoke_without_command=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
voice_app = typer.Typer(help="Manage registered house voices.", no_args_is_help=True)
skill_app = typer.Typer(help="Create and manage reusable narration skills.", no_args_is_help=True)
profile_app = typer.Typer(help="List mastering / delivery profiles.", no_args_is_help=True)
job_app = typer.Typer(help="Inspect generation jobs.", no_args_is_help=True)
book_app = typer.Typer(help="Book project mode: multi-chapter manifests and M4B export.", no_args_is_help=True)

app.add_typer(voice_app, name="voice")
app.add_typer(skill_app, name="skill")
app.add_typer(profile_app, name="profile")
app.add_typer(job_app, name="job")
app.add_typer(book_app, name="book")

console = Console()
error_console = Console(stderr=True)


def _error(exc: SkillVoiceError) -> None:
    body = Group(
        Text.from_markup(f"[bold red]{exc.__class__.__name__}[/]  {exc}"),
        Text.from_markup(f"[dim]Stage[/]  {exc.stage}"),
        Text.from_markup(f"[dim]Job[/]    {exc.job_id or '—'}"),
        Text.from_markup(f"[bold green]Fix[/]    {exc.remedy}"),
    )
    error_console.print(
        Panel(body, title="[bold red]Error[/]", border_style="red", box=box.ROUNDED)
    )


def _success(message: str, details: dict[str, str] | None = None) -> None:
    lines = [Text.from_markup(f"[bold green]✓[/]  {message}")]
    if details:
        for k, v in details.items():
            lines.append(Text.from_markup(f"   [dim]{k}:[/] {v}"))
    console.print(Panel(Group(*lines), border_style="green", box=box.ROUNDED, padding=(0, 1)))


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    if version:
        console.print(f"[bold cyan]skillvoice[/] {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def init(
    with_profile_override: bool = typer.Option(
        False,
        "--with-profile-override",
        help="Copy bundled profiles into the mutable data directory.",
    ),
) -> None:
    """Initialize the SkillVoice data directory and registry."""
    root_dir = ensure_layout()
    load_registry()
    if with_profile_override:
        install_profile_override()
    _success("Initialized", {"data dir": str(root_dir)})


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Run hard-fail environment and registry checks."""
    checks = run_checks()
    if json_output:
        console.print(checks_json(checks))
    else:
        table = Table(
            title="SkillVoice Doctor",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
            title_style="bold",
        )
        table.add_column("Check", style="bold")
        table.add_column("Status", justify="center")
        table.add_column("Detail")

        all_ok = True
        for check in checks:
            if check.ready:
                status = Text("ready", style="bold green")
            else:
                status = Text("FAIL", style="bold red")
                all_ok = False
            table.add_row(check.name, status, check.detail)

        console.print(table)
        if all_ok:
            console.print("\n[bold green]All systems ready.[/]")
        else:
            console.print("\n[bold red]One or more checks failed. Fix before production runs.[/]")
            raise typer.Exit(1)


@voice_app.command("add")
def voice_add(
    voice_id: str = typer.Argument(..., help="Short stable id, e.g. eve"),
    model: Path = typer.Argument(..., help="Path to the .onnx model file"),
    actor: str = typer.Option("", "--actor", help="Human actor name"),
    notes: str = typer.Option("", "--notes"),
    approved_uses: str = typer.Option("", "--approved-uses"),
    status: VoiceStatus = typer.Option(VoiceStatus.ACTIVE, "--status"),
) -> None:
    """Register a house voice model. Requires adjacent .onnx.json."""
    try:
        record = add_voice(
            voice_id,
            model,
            actor=actor,
            notes=notes,
            approved_uses=approved_uses,
            status=status,
        )
        _success(
            f"Voice [bold]{voice_id}[/] registered",
            {
                "sample rate": f"{record.sample_rate} Hz",
                "actor": record.actor or "—",
                "model": str(record.model),
            },
        )
    except SkillVoiceError as exc:
        _error(exc)
        raise typer.Exit(1)


@voice_app.command("list")
def voice_list() -> None:
    """List all registered voices."""
    registry = load_registry()
    if not registry:
        console.print("[dim]No voices registered. Run [bold]skillvoice voice add[/].[/]")
        return
    table = Table(
        title="Registered Voices",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Voice", style="bold")
    table.add_column("Engine")
    table.add_column("Rate", justify="right")
    table.add_column("Status")
    table.add_column("Actor")
    table.add_column("Model", overflow="fold")
    for voice_id, record in sorted(registry.items()):
        status_style = "green" if record.status.value == "active" else "yellow"
        table.add_row(
            voice_id,
            record.engine,
            str(record.sample_rate),
            Text(record.status.value, style=status_style),
            record.actor or "—",
            str(record.model),
        )
    console.print(table)


@skill_app.command("create")
def skill_create(
    name: str = typer.Argument(..., help="Skill name, e.g. eve-raspy"),
    voice: str = typer.Option(..., "--voice", help="Registered voice id"),
    profile: str = typer.Option("house", "--profile", help="Default mastering profile"),
    pace: float = typer.Option(1.0, "--pace", help="Speaking rate (1.0 = normal)"),
    energy: Energy = typer.Option(Energy.NORMAL, "--energy"),
    pitch: float = typer.Option(0.0, "--pitch", help="Pitch shift in semitones"),
    volume: float = typer.Option(1.0, "--volume"),
    style: str = typer.Option("", "--style", help="Human notes (not consumed by Piper)"),
) -> None:
    """Create a reusable skill that binds voice + attributes + defaults."""
    try:
        skill = create_skill(
            name=name,
            voice_id=voice,
            attributes=VoiceAttributes(
                pace=pace,
                energy=energy,
                pitch=pitch,
                volume=volume,
            ),
            default_profile=profile,
            style_instructions=style,
        )
        _success(
            f"Skill [bold]{name}[/] created",
            {"version": str(skill.version), "voice": skill.voice_id, "profile": skill.default_profile},
        )
    except SkillVoiceError as exc:
        _error(exc)
        raise typer.Exit(1)


@skill_app.command("update")
def skill_update(
    name: str,
    voice: Optional[str] = typer.Option(None, "--voice"),
    profile: Optional[str] = typer.Option(None, "--profile"),
    pace: Optional[float] = typer.Option(None, "--pace"),
    energy: Optional[Energy] = typer.Option(None, "--energy"),
    pitch: Optional[float] = typer.Option(None, "--pitch"),
    volume: Optional[float] = typer.Option(None, "--volume"),
    style: Optional[str] = typer.Option(None, "--style"),
) -> None:
    """Update an existing skill (bumps version)."""
    try:
        skill = update_skill(
            name,
            voice_id=voice,
            pace=pace,
            energy=energy.value if energy else None,
            pitch=pitch,
            volume=volume,
            default_profile=profile,
            style_instructions=style,
        )
        _success(f"Skill [bold]{name}[/] updated to v{skill.version}")
    except SkillVoiceError as exc:
        _error(exc)
        raise typer.Exit(1)


@skill_app.command("list")
def skill_list() -> None:
    """List all skills."""
    skills = list_skills()
    if not skills:
        console.print("[dim]No skills yet. Create one with [bold]skillvoice skill create[/].[/]")
        return
    table = Table(title="Skills", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Skill", style="bold")
    table.add_column("Version", justify="right")
    table.add_column("Voice")
    table.add_column("Profile")
    for skill in skills:
        table.add_row(
            skill.name,
            str(skill.version),
            skill.voice_id,
            skill.default_profile,
        )
    console.print(table)


@skill_app.command("show")
def skill_show(name: str) -> None:
    """Show full skill definition as JSON."""
    try:
        console.print_json(load_skill(name).model_dump_json())
    except SkillVoiceError as exc:
        _error(exc)
        raise typer.Exit(1)


@profile_app.command("list")
def profile_list() -> None:
    """List available mastering / delivery profiles."""
    table = Table(title="Mastering Profiles", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Profile", style="bold")
    table.add_column("LUFS", justify="right")
    table.add_column("True Peak", justify="right")
    table.add_column("LRA", justify="right")
    table.add_column("Rate", justify="right")
    table.add_column("Default format")
    for profile in load_profiles().values():
        table.add_row(
            profile.name,
            str(profile.loudness_lufs),
            f"{profile.true_peak_dbtp} dBTP",
            str(profile.lra),
            f"{profile.delivery_sample_rate} Hz",
            profile.default_format,
        )
    console.print(table)


@app.command()
def generate(
    skill: str = typer.Option(..., "--skill", "-s", help="Skill name"),
    text_file: Path = typer.Option(..., "--text-file", "-t", help="UTF-8 manuscript or chapter"),
    format: Optional[str] = typer.Option(None, "--format", "-f", help="wav | mp3 | m4b"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Mastering profile override"),
    resume: Optional[str] = typer.Option(None, "--resume", "-r", help="Resume an existing job ID"),
    split: bool = typer.Option(False, "--split", help="(Book mode) keep per-chapter files"),
    background: Optional[Path] = typer.Option(None, "--background", help="Optional bed audio"),
    bg_volume: float = typer.Option(0.2, "--bg-volume"),
    duck: bool = typer.Option(False, "--duck", help="Duck background under speech"),
    title: Optional[str] = typer.Option(None, "--title"),
    author: Optional[str] = typer.Option(None, "--author"),
) -> None:
    """Generate a single chapter or resume a job.

    Long books should use [bold]skillvoice book generate[/] instead.
    """
    try:
        if split:
            console.print(
                "[yellow]Note:[/] --split is primarily meaningful in book mode; "
                "a single chapter already produces one file."
            )
        console.print(f"[dim]Generating with skill [bold]{skill}[/]…[/]")
        job = run_generation(
            skill_name=skill,
            text_file=text_file,
            output_format=format,
            profile_name=profile,
            resume_job_id=resume,
            background=background,
            background_volume=bg_volume,
            duck=duck,
            title=title,
            author=author,
        )
        _success(
            "Generation complete",
            {
                "output": str(job.output_path),
                "job id": job.job_id,
                "status": job.status.value,
            },
        )
    except SkillVoiceError as exc:
        _error(exc)
        raise typer.Exit(1)


@job_app.command("show")
def job_show(job_id: str) -> None:
    """Show a job's full record."""
    try:
        console.print_json(load_job(job_id).model_dump_json())
    except SkillVoiceError as exc:
        _error(exc)
        raise typer.Exit(1)


@job_app.command("list")
def job_list() -> None:
    """List known jobs."""
    jobs_dir = data_dir() / "jobs"
    if not jobs_dir.exists():
        console.print("[dim]No jobs yet.[/]")
        return
    table = Table(title="Jobs", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Job", style="bold")
    table.add_column("Status")
    table.add_column("Skill")
    table.add_column("Updated")
    table.add_column("Output", overflow="fold")
    for path in sorted(jobs_dir.glob("*.json")):
        try:
            job = load_job(path.stem)
            status_style = {
                "completed": "green",
                "error": "red",
                "running": "yellow",
            }.get(job.status.value, "white")
            table.add_row(
                job.job_id,
                Text(job.status.value, style=status_style),
                job.skill,
                job.updated,
                str(job.output_path or "—"),
            )
        except Exception:
            table.add_row(path.stem, Text("corrupt", style="red"), "", "", "")
    console.print(table)


@book_app.command("init")
def book_init(path: Path = typer.Argument(Path("book.json"), help="Manifest path")) -> None:
    """Create a starter book.json manifest."""
    if path.exists():
        error_console.print(Panel(f"[red]{path} already exists[/]", border_style="red"))
        raise typer.Exit(1)
    init_manifest(path)
    _success(f"Created book manifest", {"path": str(path)})


@book_app.command("show")
def book_show(path: Path) -> None:
    """Show a book manifest."""
    try:
        console.print_json(load_manifest(path).model_dump_json())
    except SkillVoiceError as exc:
        _error(exc)
        raise typer.Exit(1)


@book_app.command("generate")
def book_generate(
    path: Path = typer.Argument(..., help="book.json path"),
    split: bool = typer.Option(False, "--split", help="Also keep individual chapter files"),
) -> None:
    """Render an entire book from a manifest into a chaptered M4B (or other format)."""
    try:
        console.print(f"[dim]Book generation from [bold]{path}[/]…[/]")
        output, split_outputs = generate_book(path, split=split)
        details = {"output": str(output)}
        if split_outputs:
            details["chapters"] = f"{len(split_outputs)} files"
        _success("Book complete", details)
        for item in split_outputs:
            console.print(f"  [dim]•[/] {item}")
    except SkillVoiceError as exc:
        _error(exc)
        raise typer.Exit(1)


@app.command()
def qc(
    file: Path = typer.Argument(..., help="Rendered audio file to validate"),
    profile: str = typer.Option(..., "--profile", "-p", help="Profile to check against"),
) -> None:
    """Run QC against a mastering profile. Do not ship failures."""
    try:
        profiles = load_profiles()
        selected = profiles.get(profile)
        if selected is None:
            raise SkillVoiceError(
                f"Unknown mastering profile: {profile}",
                remedy="Run `skillvoice profile list`.",
                stage="qc",
            )
        report = validate_output(file, selected)
        _success("QC PASS", {"file": str(file), "profile": profile})
        console.print_json(json.dumps(report, default=str))
    except SkillVoiceError as exc:
        _error(exc)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
