"""Command-line entry point.

This module stays thin on purpose: it parses arguments, calls into the library
packages (ingest, storage, predict, ...) and renders results. Keeping logic out of
the CLI makes it testable without a terminal and reusable from other front ends
(e.g. the planned browser extension).
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tokcast import __version__, config
from tokcast.ingest import pipeline
from tokcast.ingest.sources import ClaudeCodeSource
from tokcast.storage import db

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
) -> None:
    """Load Claude Code session logs into the local database. Safe to re-run."""
    root = path or config.claude_logs_dir()
    if not root.is_dir():
        console.print(f"[red]Log folder not found:[/] {root}")
        raise typer.Exit(1)

    with db.connect(config.db_path()) as con:
        report = pipeline.ingest(con, ClaudeCodeSource(), root, store_text=not no_text, full=full)

    table = Table(title="Ingest summary", show_header=False, box=None)
    table.add_row("Log files found", str(report.files_seen))
    table.add_row("  read (new or changed)", str(report.files_parsed))
    table.add_row("  skipped (unchanged)", str(report.files_skipped))
    table.add_row("Prompts (turns)", f"{report.prompts_after}  [green](+{report.new_prompts})[/]")
    table.add_row("API requests", f"{report.requests_after}  [green](+{report.new_requests})[/]")
    if report.errors:
        table.add_row("Malformed lines", f"[yellow]{report.errors}[/] (skipped, see ingest_errors)")
    console.print(table)
    console.print(f"[dim]Database: {config.db_path()}[/]")
