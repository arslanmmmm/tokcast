"""Terminal output (Rich). Turns report data into tables; contains no analysis logic."""

import json
from datetime import UTC, datetime

from rich.console import Console, Group
from rich.markup import escape  # user text (prompts, project names) must never be markup
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tokcast.calibrate import MIN_POINTS, Calibration
from tokcast.calibrate.mapping import MIN_PCT
from tokcast.evaluate import BacktestResult
from tokcast.predict import Estimate, Forecast, Range
from tokcast.stats import StatsReport


def fmt_tokens(n: float | int | None) -> str:
    """1234 -> '1.2k', 3_400_000 -> '3.4M'. Token counts are easier to scan this way."""
    if n is None:
        return "-"
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= limit:
            value = n / limit
            return f"{value:.1f}{suffix}" if value < 100 else f"{value:.0f}{suffix}"
    return f"{n:.0f}"


def _bar(value: float, maximum: float, width: int = 16) -> str:
    if not maximum:
        return ""
    return "█" * max(1, round(width * value / maximum)) if value else ""


def _table(title: str, *columns: str, right: tuple[str, ...] = ()) -> Table:
    table = Table(title=title, title_justify="left", title_style="bold", box=None, pad_edge=False)
    for col in columns:
        table.add_column(col, justify="right" if col in right else "left", no_wrap=True)
    return table


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

    t = _table(
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
    t = _table(
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
            Text(_bar(r["total_tokens"], peak), style="cyan"),
        )
    console.print(t, "")

    t = _table(
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

    t = _table(
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

    t = _table(
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

    t = _table(
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
    t = _table(
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


def _range(r: Range) -> str:
    return f"{fmt_tokens(r.low)} – {fmt_tokens(r.high)}"  # noqa: RUF001 (a range dash, on purpose)


def _basis(e: Estimate) -> str:
    if e.level == "prior":
        return "built-in assumption"
    assumed = [a.split(" x")[0] for a in e.adjustments if a.endswith("(assumed)")]
    basis = f"{e.group}, n={e.n}"
    return basis + (f"; assumed: {', '.join(assumed)}" if assumed else "")


def _pct_range(p: tuple[float, float, float] | None) -> str:
    if not p:
        return "-"
    low, _, high = p
    return f"~{low:.1f}–{high:.1f}%" if high < 10 else f"~{low:.0f}–{high:.0f}%"  # noqa: RUF001


def _limit_notes(f: Forecast, console: Console, show_limit: bool) -> None:
    """Where this turn would leave you, if a current usage reading exists."""
    if not show_limit:
        if f.history_turns:
            console.print(
                Text(
                    f"% of your usage limit appears after {MIN_POINTS} readings "
                    f"(have {f.limit_readings}): tokcast calibrate --used <percent>.",
                    style="dim",
                )
            )
        return
    now, mine = f.limit_now, f.estimates[0].limit_pct
    if now is None or mine is None:
        return
    left = max(100 - now.used_pct, 0)
    console.print(
        f"Now: [bold]{now.used_pct:.0f}%[/] of your 5h limit used "
        f"(resets {_local(now.resets_at):%H:%M}). This turn would take you to "
        f"~{now.used_pct + mine[1]:.0f}% (median)."
    )
    if mine[2] > left:
        console.print(
            f"[yellow]Careful:[/] the expensive end (~{mine[2]:.0f}%) wouldn't fit in the "
            f"~{left:.0f}% left. A cheaper option above, or waiting for the reset, would."
        )


def render_forecast(f: Forecast, console: Console) -> None:
    c = f.classification
    matched = ", ".join(f'"{w}"' for w in c.matched) if c.matched else "no keywords"
    context = (
        f"{f.context.mode} ≈ {fmt_tokens(f.context.tokens)} tokens"
        + (f" ({f.context.note})" if f.context.note else "")
        + f" + prompt ≈ {fmt_tokens(f.context.prompt_tokens)}"
    )
    header = Text.assemble(
        ("Task: ", "dim"),
        (c.task_type, "bold"),
        f"  (matched {matched})\n",
        ("Context: ", "dim"),
        context,
    )
    console.print(Panel(header, title="tokcast predict", title_align="left", expand=False))

    show_limit = any(e.limit_pct for e in f.estimates)
    limit_col = f"% of {f.limit_window} limit" if show_limit else None
    t = _table(
        "Estimated tokens for this turn (80% range, median)",
        *("", "model", "effort", "processed", "median", "written by model"),
        *([limit_col] if limit_col else []),
        "basis",
        right=("processed", "median", "written by model", limit_col or ""),
    )
    t.columns[-1].no_wrap = False
    for i, e in enumerate(f.estimates):
        t.add_row(
            "▶" if i == 0 else "",
            e.model,
            e.effort,
            _range(e.total),
            Text(fmt_tokens(e.total.median), style="bold" if i == 0 else ""),
            _range(e.output),
            *([_pct_range(e.limit_pct)] if show_limit else []),
            Text(_basis(e), style="dim"),
        )
    console.print(t)
    if f.estimates[0].adjustments:
        console.print(Text("Adjustments: " + "; ".join(f.estimates[0].adjustments), style="dim"))

    _limit_notes(f, console, show_limit)

    if f.similar:
        console.print("\n[bold]Similar past prompts[/]")
        for s in f.similar:
            console.print(
                f'  "{escape(s["text"][:50])}" → [bold]{fmt_tokens(s["total_tokens"])}[/]'
                f" [dim]({s['model']}·{s['effort']}, {s['ts']:%b %d})[/]",
                soft_wrap=True,
            )
    if f.new_chat:
        console.print(
            f"\n[yellow]Tip:[/] in a new chat this would be ≈ "
            f"{fmt_tokens(f.new_chat.total.median)} instead of "
            f"{fmt_tokens(f.estimates[0].total.median)} (median)."
        )
    if f.history_turns == 0:
        console.print(
            "\n[yellow]No history yet[/]: these are built-in assumptions. "
            "Run [bold]tokcast ingest[/] to learn from your own usage."
        )
    console.print(
        Text(
            "\nEstimates, not guarantees: about 8 in 10 similar turns should fall inside the "
            "range. How much the model writes is inherently uncertain.",
            style="dim",
        )
    )


_OURS = "tokcast baseline"


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _scores_table(title: str, result: BacktestResult, target: str) -> Table:
    numbers = ("in range", "low", "high", "≤2x", "bias", "width", "pinball", "vs baseline")
    t = _table(title, "method", *numbers, right=numbers)
    t.columns[0].no_wrap = False  # long method names wrap; the numbers never do
    for m in result.methods:
        s = getattr(m, target)
        style = "bold" if m.name == _OURS else ""
        t.add_row(
            Text(m.name, style=style),
            Text(f"{_pct(s.coverage)} ±{s.coverage_margin * 100:.0f}", style=style),
            _pct(s.above),  # actual above the range: the forecast was too low
            _pct(s.below),
            _pct(s.within_2x),
            f"x{s.bias:.2f}",
            f"x{s.width:.0f}",
            Text(f"{s.pinball:.3f}", style=style),
            _vs_baseline(m) if target == "total" else "",
        )
    return t


def _vs_baseline(m) -> Text:
    """Paired difference in pinball loss: green if clearly better, red if clearly worse."""
    if m.vs_baseline is None:
        return Text("")
    mean, low, high = m.vs_baseline
    style = "green" if high < 0 else "red" if low > 0 else "dim"  # interval excludes zero?
    return Text(f"{mean:+.3f}", style=style)


def render_backtest(result: BacktestResult, console: Console) -> None:
    source = "synthetic data" if result.data == "synthetic" else "your real history"
    header = Text.assemble(
        "Backtest on ",
        (source, "bold"),
        f": {result.n_turns:,} turns ({result.first_ts:%Y-%m-%d} → {result.last_ts:%Y-%m-%d}).\n",
        f"Each of the newest {result.n_test:,} turns (from {result.test_from:%Y-%m-%d}) "
        f"was predicted using only older turns, in {result.folds} walk-forward folds.",
    )
    console.print(Panel(header, title="tokcast eval", title_align="left", expand=False))
    console.print(_scores_table("Tokens processed per turn", result, "total"), "")
    console.print(_scores_table("Tokens written per turn", result, "output"), "")

    ours, best = result.method(_OURS).total, min(result.methods, key=lambda m: m.total.pinball)
    console.print(
        f"[bold]{_OURS}[/]: {_pct(ours.coverage)} of actual totals fell inside its 80% range, "
        f"and {_pct(ours.within_2x)} of its medians were within 2x of the real value."
    )
    if best.name != _OURS:
        console.print(f"[yellow]Note:[/] on this data, '{best.name}' scored best (pinball loss).")
    if result.data == "synthetic":
        console.print(
            "[yellow]Synthetic data:[/] this checks that the pipeline works, not how accurate "
            "predictions are on real usage. The generator shares the built-in assumptions."
        )
    if result.n_test < 100:
        margin = result.method(_OURS).total.coverage_margin
        console.print(
            f"[yellow]Small test set ({result.n_test} turns):[/] coverage is only known "
            f"to about ±{margin * 100:.0f} points. Differences between methods may be noise."
        )
    console.print(
        Text(
            "in range: share of actual values inside the 80% range (target 80%). low/high: "
            "forecast too low/high. ≤2x: median within a factor 2. bias: typical "
            "forecast/actual. width: typical high/low. pinball: quantile loss, lower is better. "
            "vs baseline: paired pinball difference on the same turns; green/red = the 95% "
            "interval excludes zero (clearly better/worse), grey = within noise.",
            style="dim",
        )
    )


def backtest_markdown(result: BacktestResult) -> str:
    """The results as a Markdown table, for the README."""
    source = "synthetic" if result.data == "synthetic" else "real"
    lines = [
        f"Backtest on {source} data: {result.n_turns:,} turns, the newest {result.n_test:,} "
        f"predicted walk-forward in {result.folds} folds (tokens processed per turn).",
        "",
        "| method | in 80% range | within 2x | bias | width | pinball loss "
        "| vs baseline (95% CI) |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in result.methods:
        s, name = m.total, f"**{m.name}**" if m.name == _OURS else m.name
        vs = "" if m.vs_baseline is None else "{:+.3f} [{:+.3f}, {:+.3f}]".format(*m.vs_baseline)
        lines.append(
            f"| {name} | {_pct(s.coverage)} ±{s.coverage_margin * 100:.0f} | {_pct(s.within_2x)} "
            f"| x{s.bias:.2f} | x{s.width:.0f} | {s.pinball:.3f} | {vs} |"
        )
    return "\n".join(lines)


def _local(dt: datetime) -> datetime:
    """Naive UTC -> local time, for display."""
    return dt.replace(tzinfo=UTC).astimezone()


def render_statusline_setup(console: Console) -> None:
    console.print(
        "tokcast can record your usage-limit readings automatically. Claude Code shows them "
        "to its status-line command (claude.ai Pro and Max plans, after the first reply).\n"
        "Add this to [bold]~/.claude/settings.json[/] (tokcast doesn't edit it for you):\n"
    )
    snippet = json.dumps(
        {"statusLine": {"type": "command", "command": "tokcast statusline"}}, indent=2
    )
    console.print(Panel(Text(snippet), expand=False))
    console.print(
        "If you already have a status line, keep it: add tokcast to the same command, e.g.\n"
        "  [dim]tee >(tokcast statusline >/dev/null) | your-existing-command[/]\n"
        "Readings are appended to a local file and loaded by [bold]tokcast ingest[/] or "
        "[bold]tokcast calibrate[/]. Nothing leaves your machine."
    )


def render_calibration(c: Calibration, console: Console) -> None:
    label = {"5h": "5-hour", "7d": "7-day"}[c.window]
    if c.points:
        t = _table(
            f"Usage readings for the {label} limit",
            *("taken", "source", "used", "weighted tokens", "% per 1M"),
            right=("used", "weighted tokens", "% per 1M"),
        )
        for p in c.points[-10:]:
            t.add_row(
                f"{_local(p['ts']):%Y-%m-%d %H:%M}",
                p["source"],
                f"{p['used_pct']:.0f}%",
                fmt_tokens(p["weighted_tokens"]),
                f"{p['pct_per_million']:.2f}",
            )
        console.print(t, "")
    if c.skipped:
        console.print(
            f"[dim]{c.skipped} reading(s) not used yet: under {MIN_PCT:.0f}% (too coarse) or "
            "taken after the last ingested call (run tokcast ingest).[/]"
        )
    if not c.ready:
        console.print(
            f"[yellow]{len(c.points)} of {MIN_POINTS} readings[/] needed before predictions show "
            f"% of your {label} limit. Record one with "
            "[bold]tokcast calibrate --used <percent>[/], or let [bold]tokcast statusline[/] "
            "collect them (see tokcast statusline --setup)."
        )
        return
    per_pct = 1e6 / c.k
    typical = per_pct / c.turn_weight if c.turn_weight else None
    console.print(
        f"[bold]1% of your {label} limit ≈ {fmt_tokens(per_pct)} weighted tokens[/]"
        + (f" ≈ {fmt_tokens(typical)} tokens processed in a typical turn" if typical else "")
        + f"  (from {len(c.points)} readings; spread {c.k_low:.2f}-{c.k_high:.2f} % per 1M)."
    )
    console.print(
        Text(
            "Estimates: Anthropic doesn't publish how limits count tokens. Usage outside this "
            "machine's Claude Code (claude.ai, other computers) isn't in your logs, which makes "
            "these percentages err on the high side.",
            style="dim",
        )
    )
