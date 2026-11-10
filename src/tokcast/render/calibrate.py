"""`tokcast calibrate` and `statusline --setup`."""

import json

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from tokcast.calibrate import MIN_POINTS, Calibration
from tokcast.calibrate.mapping import MIN_PCT
from tokcast.render.common import fmt_tokens, make_table, to_local


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
        t = make_table(
            f"Usage readings for the {label} limit",
            *("taken", "source", "used", "weighted tokens", "% per 1M"),
            right=("used", "weighted tokens", "% per 1M"),
        )
        for p in c.points[-10:]:
            t.add_row(
                f"{to_local(p['ts']):%Y-%m-%d %H:%M}",
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
    if c.k is None:  # ready implies a k; this keeps the division safe if that changes
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
