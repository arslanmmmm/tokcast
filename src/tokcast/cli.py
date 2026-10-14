"""Command-line entry point.

This module stays thin on purpose: it parses arguments, calls into the library
packages (ingest, storage, predict, ...) and renders results. Keeping logic out of
the CLI makes it testable without a terminal and reusable from other front ends
(e.g. the planned browser extension).
"""

import shlex
import shutil
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tokcast import __version__, config
from tokcast.ingest import pipeline
from tokcast.ingest.sources import ClaudeCodeSource
from tokcast.storage import db
from tokcast.synth import generator as synth_gen

app = typer.Typer(
    help="Forecast Claude Code token usage before you send a prompt. Local-only.",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"tokcast {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version."
    ),
) -> None:
    """tokcast: a forecast for your tokens."""


@app.command()
def paths() -> None:
    """Show where tokcast reads logs from and stores its database."""
    console.print(f"[bold]Claude Code logs:[/] {config.claude_logs_dir()}")
    console.print(f"[bold]tokcast database:[/] {config.db_path()}")


@app.command()
def ingest(
    path: Path | None = typer.Option(
        None, "--path", help="Log folder to read. Default: ~/.claude/projects"
    ),
    no_text: bool = typer.Option(
        False, "--no-text", help="Don't store prompt text, only its length and a hash."
    ),
    full: bool = typer.Option(False, "--full", help="Re-read every file, even unchanged ones."),
    allow_synthetic: bool = typer.Option(
        False, "--allow-synthetic", help="Load synthetic logs into the default database anyway."
    ),
) -> None:
    """Load Claude Code session logs into the local database. Safe to re-run."""
    root = path or config.claude_logs_dir()
    if not root.is_dir():
        console.print(f"[red]Log folder not found:[/] {root}")
        raise typer.Exit(1)
    # Synthetic rows can't be told apart from real ones later, so keep them out of the
    # real database unless the user explicitly points tokcast at a separate one.
    if synth_gen.is_synthetic(root) and config.uses_default_data_dir() and not allow_synthetic:
        console.print(
            "[red]This folder contains synthetic logs.[/] Load them into a separate "
            "database so they don't mix with your real history, e.g.:"
        )
        console.print(
            f"  TOKCAST_HOME={_demo_home(root)} tokcast ingest --path {root}", soft_wrap=True
        )
        raise typer.Exit(1)

    with db.connect(config.db_path()) as con:
        report = pipeline.ingest(con, ClaudeCodeSource(), root, store_text=not no_text, full=full)

    table = Table(title="Ingest summary", show_header=False, box=None)
    table.add_column(no_wrap=True)  # labels stay on one line in narrow terminals
    table.add_column(no_wrap=True)
    table.add_row("Log files found", str(report.files_seen))
    table.add_row("  read (new or changed)", str(report.files_parsed))
    table.add_row("  skipped (unchanged)", str(report.files_skipped))
    table.add_row("Prompts (turns)", f"{report.prompts_after}  [green](+{report.new_prompts})[/]")
    table.add_row("API requests", f"{report.requests_after}  [green](+{report.new_requests})[/]")
    if report.errors:
        table.add_row("Malformed lines", f"[yellow]{report.errors}[/] (skipped, see ingest_errors)")
    console.print(table)
    # soft_wrap: let the terminal wrap long paths itself instead of Rich splitting them.
    console.print(f"[dim]Database: {config.db_path()}[/]", soft_wrap=True)


@app.command()
def synth(
    out: Path = typer.Option(Path("tokcast-demo"), "--out", help="Folder to write into."),
    sessions: int = typer.Option(200, "--sessions", min=1, help="Number of sessions."),
    days: int = typer.Option(60, "--days", min=1, help="Spread sessions over this many days."),
    seed: int = typer.Option(42, "--seed", help="Same seed, same data."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing synthetic logs."),
) -> None:
    """Generate realistic fake Claude Code logs for demos and testing."""
    logs = out / "logs"
    if logs.exists() and any(logs.iterdir()):
        if not force:
            console.print(f"[red]{logs} is not empty.[/] Use --force to replace it.")
            raise typer.Exit(1)
        if not synth_gen.is_synthetic(logs):  # never delete anything we didn't generate
            console.print(
                f"[red]{logs} doesn't look like tokcast synthetic data; not touching it.[/]"
            )
            raise typer.Exit(1)

        shutil.rmtree(logs)

    started = time.perf_counter()
    summary = synth_gen.generate(logs, sessions=sessions, days=days, seed=seed)
    seconds = time.perf_counter() - started

    console.print(
        f"Generated [bold]{summary.sessions}[/] sessions, [bold]{summary.prompts}[/] turns and "
        f"[bold]{summary.requests + summary.subagent_requests}[/] API calls "
        f"({summary.subagent_requests} by subagents) in {seconds:.1f}s.",
        soft_wrap=True,
    )
    console.print("[yellow]These logs are synthetic, not real usage.[/] Load them with:")
    console.print(
        f"  TOKCAST_HOME={_demo_home(logs)} tokcast ingest --path {shlex.quote(str(logs))}",
        soft_wrap=True,
    )


def _demo_home(logs: Path) -> str:
    """A database location next to the synthetic logs, e.g. tokcast-demo/db."""
    return shlex.quote(str(logs.parent / "db"))
