"""Command-line entry point.

This module stays thin on purpose: it parses arguments, calls into the library
packages (ingest, storage, predict, ...) and renders results. Keeping logic out of
the CLI makes it testable without a terminal and reusable from other front ends
(e.g. the planned browser extension).
"""

import json
import re
import shlex
import shutil
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from tokcast import __version__, config
from tokcast.synth import generator as synth_gen  # standard library only: cheap to import

# Heavy libraries (pandas, DuckDB, pyarrow, numpy) are imported inside the commands that
# need them. `tokcast statusline` runs after every Claude reply and must start fast; with
# everything imported up front it took ~1.1 s, almost all of it pandas.

PIP_ML = "pip install 'tokcast[ml]'"

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
            f"  TOKCAST_HOME={_demo_home(root)} tokcast ingest --path {shlex.quote(str(root))}",
            soft_wrap=True,
        )
        raise typer.Exit(1)

    from tokcast.calibrate import load_file
    from tokcast.ingest import pipeline
    from tokcast.ingest.sources import ClaudeCodeSource
    from tokcast.storage import db

    with db.connect(config.db_path()) as con:
        report = pipeline.ingest(con, ClaudeCodeSource(), root, store_text=not no_text, full=full)
        readings = load_file(con, config.data_dir())  # captured by `tokcast statusline`

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
    if readings:
        table.add_row("Usage-limit readings", str(readings))
    console.print(table)
    # soft_wrap: let the terminal wrap long paths itself instead of Rich splitting them.
    console.print(f"[dim]Database: {config.db_path()}[/]", soft_wrap=True)


@app.command()
def stats(
    days: int | None = typer.Option(None, "--days", min=1, help="Only the last N days."),
    top: int = typer.Option(5, "--top", min=1, help="How many expensive sessions to list."),
    tz: str | None = typer.Option(
        None, "--tz", help="Time zone for daily totals, e.g. Asia/Almaty. Default: system."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Summarize your history: tokens by model, day and project, and what drives cost."""
    from tokcast import render
    from tokcast.stats import build_report
    from tokcast.storage import db

    if not config.db_path().exists():
        console.print("No data yet. Run [bold]tokcast ingest[/] first.")
        raise typer.Exit(1)
    with db.connect(config.db_path()) as con:
        if tz:
            try:
                ZoneInfo(tz)  # validate before putting it into SQL
            except (ZoneInfoNotFoundError, ValueError):
                console.print(f"[red]Unknown time zone:[/] {tz}")
                raise typer.Exit(1) from None
            con.execute(f"SET TimeZone = '{tz}'")
        report = build_report(con, days=days, top=top)

    if as_json:
        print(json.dumps(asdict(report), default=str, indent=2))
    elif report.is_empty:
        console.print("No turns in this period. Try without --days, or run tokcast ingest.")
    else:
        render.render_stats(report, console)


@app.command()
def predict(
    prompt: str = typer.Argument(..., help='The prompt you are about to send. Use "-" for stdin.'),
    model: str | None = typer.Option(
        None, "--model", "-m", help="opus, sonnet, haiku or fable. Default: your latest model."
    ),
    effort: str | None = typer.Option(
        None, "--effort", "-e", help="low, medium, high, xhigh or max. Default: your latest."
    ),
    context: str | None = typer.Option(
        None, "--context", help="Current conversation size, e.g. 120k. Default: a new chat."
    ),
    continue_: bool = typer.Option(
        False, "--continue", "-c", help="Continue your most recent conversation (as of ingest)."
    ),
    compare: bool = typer.Option(True, "--compare/--no-compare", help="Show alternatives."),
    method: str = typer.Option(
        "baseline", "--method", help="baseline, or qreg (quantile regression; needs tokcast[ml])."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Estimate how many tokens a prompt will use, before you send it."""
    import pandas as pd

    from tokcast import calibrate as cal
    from tokcast import render
    from tokcast.features.build import current_conversation, load_turns, new_chat_context
    from tokcast.predict import forecast, priors
    from tokcast.storage import db

    predictor = _predictor(method)
    if prompt == "-":
        prompt = sys.stdin.read()
    if context and continue_:
        console.print("[red]Use either --context or --continue, not both.[/]")
        raise typer.Exit(1)

    turns, conversation, fresh, fresh_n = None, None, None, 0
    calibration, weekly, reading = None, None, None
    if config.db_path().exists():
        with db.connect(config.db_path()) as con:
            turns = load_turns(con)
            conversation = current_conversation(con)
            fresh, fresh_n = new_chat_context(con)
            cal.load_file(con, config.data_dir())  # pick up the latest status-line readings
            calibration = cal.fit(con, "5h")
            weekly = cal.fit(con, "7d")
            reading = cal.latest_reading(con, "5h", cal.utcnow())
    if turns is None:
        turns = pd.DataFrame()  # no history: predictions fall back to assumptions

    model = _model_family(model or (conversation.model if conversation else "opus"))
    effort = (effort or (conversation.effort if conversation else None) or "medium").lower()
    if effort not in priors.EFFORTS:
        console.print(f"[red]Unknown effort:[/] {effort} (use {', '.join(priors.EFFORTS)})")
        raise typer.Exit(1)

    if continue_:
        if conversation is None:
            console.print("[red]No conversation found.[/] Run tokcast ingest first.")
            raise typer.Exit(1)
        mode, tokens, note = (
            "continue",
            None,
            f"last conversation, {conversation.ts:%b %d %H:%M} UTC",
        )
    elif context:
        mode, tokens, note = "given", _parse_tokens(context), "from --context"
    else:
        mode, tokens = "new chat", None
        note = f"median of your {fresh_n} first turns" if fresh_n else "built-in assumption"

    result = forecast(
        turns,
        prompt,
        model=model,
        effort=effort,
        context_mode=mode,
        context_tokens=tokens,
        context_note=note,
        conversation=conversation,
        new_chat_tokens=fresh or None,
        compare=compare,
        predictor=predictor,
        calibration=calibration,
        reading=reading,
        weekly=weekly,
    )
    if as_json:
        print(json.dumps(asdict(result), default=str, indent=2))
    else:
        render.render_forecast(result, console)


def _predictor(method: str):
    from tokcast.evaluate.reference import ml_available
    from tokcast.predict import BaselinePredictor

    if method == "baseline":
        return BaselinePredictor()
    if method == "qreg":
        if not ml_available():
            # escape(): Rich would otherwise read "[ml]" as a style tag and drop it.
            console.print(f"[red]--method qreg needs scikit-learn:[/] {escape(PIP_ML)}")
            raise typer.Exit(1)
        from tokcast.predict.qreg import QuantileRegressionPredictor

        return QuantileRegressionPredictor("linear")
    console.print(f"[red]Unknown method:[/] {method} (use baseline or qreg)")
    raise typer.Exit(1)


def _model_family(name: str) -> str:
    """'opus', 'Opus' or 'claude-opus-5-5' -> 'opus'."""
    from tokcast.predict import priors

    match = re.search(r"opus|sonnet|haiku|fable", name.lower())
    if not match:
        console.print(f"[red]Unknown model:[/] {name} (use {', '.join(priors.MODELS)})")
        raise typer.Exit(1)
    return match.group(0)


def _parse_duration(text: str) -> timedelta:
    """'2h10m' -> 2 hours 10 minutes. Days, hours and minutes, in that order."""
    match = re.fullmatch(r"\s*(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*", text.lower())
    if not match or not any(match.groups()):
        console.print(f"[red]Can't read duration:[/] {text} (try 2h10m or 3d4h)")
        raise typer.Exit(1)
    days, hours, minutes = (int(g or 0) for g in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes)


def _parse_tokens(text: str) -> float:
    """'120k' -> 120000, '1.5M' -> 1500000, '50000' -> 50000."""
    match = re.fullmatch(r"\s*([\d.]+)\s*([km]?)\s*", text.lower())
    if not match:
        console.print(f"[red]Can't read token count:[/] {text} (try 120k or 1.5M)")
        raise typer.Exit(1)
    return float(match.group(1)) * {"": 1, "k": 1e3, "m": 1e6}[match.group(2)]


@app.command("eval")
def eval_(
    folds: int = typer.Option(5, "--folds", min=1, help="Walk-forward folds."),
    test_fraction: float = typer.Option(
        0.5, "--test-fraction", min=0.1, max=0.9, help="Share of newest turns used as test set."
    ),
    synthetic: int | None = typer.Option(
        None, "--synthetic", min=10, help="Evaluate on N generated sessions instead."
    ),
    seed: int = typer.Option(42, "--seed", help="Seed for --synthetic."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    markdown: bool = typer.Option(False, "--markdown", help="Print a Markdown table."),
) -> None:
    """Backtest the predictor on past turns: how often were the ranges right?"""
    from tokcast import render
    from tokcast.evaluate import backtest
    from tokcast.features.build import load_turns
    from tokcast.ingest import pipeline
    from tokcast.ingest.sources import ClaudeCodeSource
    from tokcast.storage import db

    if synthetic:
        with tempfile.TemporaryDirectory() as tmp:
            synth_gen.generate(Path(tmp), sessions=synthetic, seed=seed)
            with db.connect(":memory:") as con:
                pipeline.ingest(con, ClaudeCodeSource(), Path(tmp))
                turns, data = load_turns(con), "synthetic"
    else:
        if not config.db_path().exists():
            console.print("No data yet. Run [bold]tokcast ingest[/] first, or try --synthetic 300.")
            raise typer.Exit(1)
        with db.connect(config.db_path()) as con:
            turns = load_turns(con)
            data = "synthetic" if synth_gen.is_synthetic_db(con) else "real"

    try:
        result = backtest(turns, data=data, folds=folds, test_fraction=test_fraction)
    except ValueError as exc:
        console.print(
            f"[yellow]Not enough history to evaluate:[/] {exc}. Keep using Claude Code and "
            f"re-run tokcast ingest, or try [bold]tokcast eval --synthetic 300[/]."
        )
        raise typer.Exit(1) from None
    if as_json:
        print(json.dumps(asdict(result), default=str, indent=2))
    elif markdown:
        print(render.backtest_markdown(result))
    else:
        render.render_backtest(result, console)


@app.command()
def calibrate(
    used: float | None = typer.Option(
        None, "--used", min=0, max=100, help="Usage percent Claude shows right now, e.g. 23."
    ),
    window: str = typer.Option("5h", "--window", help="Which limit: 5h or 7d."),
    resets_in: str | None = typer.Option(
        None, "--resets-in", help="Time until the window resets, as Claude shows it: 2h10m."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Teach tokcast your tokens -> "% of usage limit" mapping (estimates, clearly labelled)."""
    from tokcast import calibrate as cal
    from tokcast import render
    from tokcast.calibrate.mapping import WINDOW_LENGTH
    from tokcast.ingest import pipeline
    from tokcast.ingest.sources import ClaudeCodeSource
    from tokcast.storage import db

    if window not in WINDOW_LENGTH:
        console.print("[red]--window must be 5h or 7d[/]")
        raise typer.Exit(1)
    with db.connect(config.db_path()) as con:
        # Token counts must be current for the reading to be matched against them.
        logs = config.claude_logs_dir()
        if logs.is_dir() and not synth_gen.is_synthetic(logs):
            pipeline.ingest(con, ClaudeCodeSource(), logs)
        cal.load_file(con, config.data_dir())

        if used is not None:
            now = cal.utcnow()
            if resets_in:
                resets_at = now + _parse_duration(resets_in)
            elif window == "5h":
                resets_at = cal.infer_window_end(con, now)
            else:
                resets_at = None
            if resets_at is None:
                console.print(
                    "[red]Can't tell when this window started.[/] Add --resets-in "
                    "(Claude's usage screen shows it, e.g. --resets-in 2h10m)."
                )
                raise typer.Exit(1)
            cal.save(con, [cal.Snapshot(window, resets_at, used, now, "manual")])
        result = cal.fit(con, window)

    if as_json:
        print(json.dumps(asdict(result) | {"ready": result.ready}, default=str, indent=2))
    else:
        render.render_calibration(result, console)


@app.command()
def statusline(
    setup: bool = typer.Option(False, "--setup", help="Show how to turn this on in Claude Code."),
) -> None:
    """Status-line command for Claude Code: records usage-limit readings, prints a summary.

    Claude Code runs it after each reply with session data on stdin. It only appends to a
    small local file (fast, never touches the database) and never fails.
    """
    if setup:
        from tokcast import render

        render.render_statusline_setup(console)
        return
    from tokcast import capture  # standard library only, so this stays fast

    print(capture.run(sys.stdin.read(), config.data_dir()))


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
