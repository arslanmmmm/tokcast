"""Command-line entry point.

This module stays thin on purpose: it parses arguments, calls into the library
packages (ingest, storage, predict, ...) and renders results. Keeping logic out of
the CLI makes it testable without a terminal and reusable from other front ends
(e.g. the planned browser extension).
"""

import typer
from rich.console import Console

from tokcast import __version__, config

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
