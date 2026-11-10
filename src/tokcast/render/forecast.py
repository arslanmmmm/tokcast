"""`tokcast predict`: the forecast table, its basis and the usage-limit notes."""

from rich.console import Console
from rich.markup import escape  # user text (prompts, project names) must never be markup
from rich.panel import Panel
from rich.text import Text

from tokcast.calibrate import MIN_POINTS
from tokcast.predict import Estimate, Forecast, Range
from tokcast.render.common import fmt_tokens, make_table, pct_range, to_local


def _range(r: Range) -> str:
    return f"{fmt_tokens(r.low)} – {fmt_tokens(r.high)}"  # noqa: RUF001 (a range dash, on purpose)


def _basis(e: Estimate) -> str:
    if e.level == "prior":
        return "built-in assumption"
    assumed = [a.split(" x")[0] for a in e.adjustments if a.endswith("(assumed)")]
    basis = f"{e.group}, n={e.n}"
    return basis + (f"; assumed: {', '.join(assumed)}" if assumed else "")


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
    if f.limit_assumed_plan:
        console.print(
            Text(
                f"% of limit is assumed: the {f.limit_assumed_plan} plan's starting guess "
                f"(fitted on one user) until {MIN_POINTS} of your own readings exist.",
                style="dim",
            )
        )
    if f.weekly_pct:
        weekly = pct_range(f.weekly_pct)
        console.print(f"Weekly: this turn would use {weekly} of your 7-day limit.")
    now, mine = f.limit_now, f.estimates[0].limit_pct
    if now is None or mine is None:
        return
    left = max(100 - now.used_pct, 0)
    console.print(
        f"Now: [bold]{now.used_pct:.0f}%[/] of your 5h limit used "
        f"(resets {to_local(now.resets_at):%H:%M}). This turn would take you to "
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
    t = make_table(
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
            *([pct_range(e.limit_pct)] if show_limit else []),
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
    if f.advice:  # the cheaper next move (predict/advice.py); replaces the old new-chat tip
        console.print("\n[bold]Cheaper next move[/] (predicted for the same task)")
        for item in f.advice:
            note = "  [dim](assumed)[/]" if item.assumed else ""
            console.print(f"  [yellow]•[/] {escape(item.message)}{note}", soft_wrap=True)
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
