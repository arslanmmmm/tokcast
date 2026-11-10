"""`tokcast stats`: the usage report and its data-quality note."""

from rich.console import Console, Group
from rich.markup import escape  # user text (prompts, project names) must never be markup
from rich.panel import Panel
from rich.text import Text

from tokcast.render.common import bar, fmt_tokens, make_table
from tokcast.stats import StatsReport


def render_stats(report: StatsReport, console: Console, *, day_rows: int = 14) -> None:
    o = report.overview
    period = "all history" if report.since is None else f"since {report.since:%Y-%m-%d}"
    cache_share = o["cache_read_tokens"] / o["total_tokens"] if o["total_tokens"] else 0
    headline = Text.assemble(
        (f"{o['turns']:,}", "bold"),
        " turns · ",
        (f"{o['api_calls']:,}", "bold"),
        " API calls · ",
        (fmt_tokens(o["total_tokens"]), "bold"),
        " tokens processed · ",
        (fmt_tokens(o["output_tokens"]), "bold"),
        " written by the model\n",
        f"{o['sessions']} sessions, {o['first_ts']:%Y-%m-%d} → {o['last_ts']:%Y-%m-%d} ",
        f"({period}). ",
        f"Median turn {fmt_tokens(o['median_turn_tokens'])}, ",
        f"90% of turns under {fmt_tokens(o['p90_turn_tokens'])}. ",
        f"{cache_share:.0%} of tokens were cache reads",
        f"; subagents {fmt_tokens(o['subagent_tokens'])}." if o["subagent_tokens"] else ".",
    )
    console.print(Panel(headline, title="tokcast stats", title_align="left", expand=False))

    t = make_table(
        "By model and effort",
        "model",
        "effort",
        "turns",
        "calls",
        "output",
        "total",
        "share",
        right=("turns", "calls", "output", "total", "share"),
    )
    for r in report.by_model:
        t.add_row(
            escape(r["model"]),
            r["effort"],
            f"{r['turns']:,}",
            f"{r['api_calls']:,}",
            fmt_tokens(r["output_tokens"]),
            fmt_tokens(r["total_tokens"]),
            f"{r['share_pct']:.0f}%",
        )
    console.print(t, "")

    days = report.by_day[-day_rows:]
    peak = max((r["total_tokens"] for r in days), default=0)
    t = make_table(
        f"By day (last {len(days)} active days)",
        "day",
        "turns",
        "total",
        "",
        right=("turns", "total"),
    )
    for r in days:
        t.add_row(
            f"{r['day']:%a %Y-%m-%d}",
            f"{r['turns']:,}",
            fmt_tokens(r["total_tokens"]),
            Text(bar(r["total_tokens"], peak), style="cyan"),
        )
    console.print(t, "")

    t = make_table(
        "By project",
        "project",
        "sessions",
        "turns",
        "total",
        "share",
        right=("sessions", "turns", "total", "share"),
    )
    for r in report.by_project:
        t.add_row(
            escape(r["project"]),
            str(r["sessions"]),
            f"{r['turns']:,}",
            fmt_tokens(r["total_tokens"]),
            f"{r['share_pct']:.0f}%",
        )
    console.print(t, "")

    t = make_table(
        "Most expensive sessions",
        "started",
        "project",
        "turns",
        "total",
        "first prompt",
        right=("turns", "total"),
    )
    t.columns[-1].overflow = "ellipsis"  # one line per session, cut off with "…"
    t.columns[-1].max_width = 40
    for r in report.top_sessions:
        first = " ".join((r["first_prompt"] or "(text not stored)").split())
        t.add_row(
            f"{r['started']:%Y-%m-%d}",
            escape(r["project"] or "-"),
            str(r["turns"]),
            fmt_tokens(r["total_tokens"]),
            escape(first[:60]),
        )
    console.print(t, "")

    t = make_table(
        "API call cost vs. conversation size",
        "context",
        "calls",
        "median call",
        "cache hit",
        right=("calls", "median call", "cache hit"),
    )
    for r in report.context_cost:
        t.add_row(
            r["context_size"],
            f"{r['api_calls']:,}",
            fmt_tokens(r["median_call_tokens"]),
            f"{r['cache_hit_rate']:.0%}" if r["cache_hit_rate"] is not None else "-",
        )
    console.print(t)
    if (ratio := report.context_cost_ratio) and ratio > 1.5:
        console.print(
            Text(
                f"Every call re-reads the whole conversation: a call in the largest bucket "
                f"costs ~{ratio:.0f}x one in the smallest. A fresh chat resets this.",
                style="dim",
            )
        )
    console.print()

    t = make_table(
        "Turns later in a conversation",
        "turn #",
        "turns",
        "median context",
        "median calls",
        "median turn",
        right=("turns", "median context", "median calls", "median turn"),
    )
    for r in report.turn_length:
        t.add_row(
            r["turn_number"],
            f"{r['turns']:,}",
            fmt_tokens(r["median_context_before"]),
            f"{r['median_api_calls']:.0f}",
            fmt_tokens(r["median_turn_tokens"]),
        )
    console.print(t, "")

    console.print(_quality_note(report))


def _quality_note(report: StatsReport) -> Group | Text:
    rows = report.data_quality
    checked = sum(r["api_calls"] for r in rows)
    flagged = [r for r in rows if r["flagged"]]
    versions = ", ".join(escape(r["version"]) for r in rows)
    if not flagged:
        return Text(
            f"✓ Data quality: no suspicious usage values in {checked:,} API calls "
            f"(Claude Code {versions}).",
            style="green",
        )
    t = make_table(
        "⚠ Data quality: suspicious usage values (kept out of predictions)",
        "version",
        "calls",
        "flagged",
        "thinking > output",
        "zero output",
        "zero input",
        right=("calls", "flagged", "thinking > output", "zero output", "zero input"),
    )
    for r in flagged:
        t.add_row(
            escape(r["version"]),
            f"{r['api_calls']:,}",
            f"{r['flagged']:,}",
            str(r["thinking_exceeds_output"]),
            str(r["zero_output"]),
            str(r["zero_input"]),
        )
    return Group(t)
