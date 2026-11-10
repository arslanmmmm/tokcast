"""`tokcast ingest`: the summary of what was loaded."""

from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from tokcast.ingest.pipeline import IngestReport


def render_ingest(report: IngestReport, readings: int, db_path: Path, console: Console) -> None:
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
    if report.failed_files:
        table.add_row(
            "Files not loaded",
            f"[red]{len(report.failed_files)}[/] (rolled back; retried on the next ingest)",
        )
    if readings:
        table.add_row("Usage-limit readings", str(readings))
    console.print(table)
    for failed, reason in report.failed_files:
        console.print(f"[red]Not loaded:[/] {escape(failed)}: {escape(reason)}", soft_wrap=True)
    # soft_wrap: let the terminal wrap long paths itself instead of Rich splitting them.
    console.print(f"[dim]Database: {db_path}[/]", soft_wrap=True)
