"""`tokcast eval` and `calibrate --backtest`: backtest tables and the Markdown summary."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tokcast.evaluate import BacktestResult
from tokcast.evaluate.backtest import MethodResult
from tokcast.evaluate.limits import LimitBacktest
from tokcast.render.common import make_table

_OURS = "tokcast baseline"


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _scores_table(title: str, result: BacktestResult, target: str) -> Table:
    numbers = ("in range", "low", "high", "≤2x", "bias", "width", "pinball", "vs baseline")
    t = make_table(title, "method", *numbers, right=numbers)
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


def _vs_baseline(m: MethodResult) -> Text:
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


def _verdict(adopt: bool | None) -> str:
    if adopt is None:
        return "no decision (too few windows)"
    return "[green]adopt increments[/]" if adopt else "keep totals"


def render_limit_backtest(results: list[LimitBacktest], console: Console) -> None:
    """Totals vs increments for each limit window, judged by the rule in docs/plan.md (10a)."""
    t = make_table(
        "% of limit calibration: forward backtest by window (rule: docs/plan.md, 10a)",
        *("limit", "test windows", "pairs", "error totals", "error increments"),
        *("improvement, 95%", "80% coverage", "decision"),
        right=("test windows", "pairs", "error totals", "error increments", "80% coverage"),
    )
    for r in results:
        label = {"5h": "5-hour", "7d": "weekly"}[r.window]
        if r.test_pairs == 0:
            t.add_row(label, "0", "0", "-", "-", "-", "-", _verdict(None))
            continue
        t.add_row(
            label,
            str(r.test_windows),
            str(r.test_pairs),
            f"{r.mae_totals:.2f} pts",
            f"{r.mae_increments:.2f} pts",
            f"{r.diff_low:+.2f} to {r.diff_high:+.2f} pts",
            f"{r.coverage:.0%}",
            _verdict(r.adopt),
        )
    console.print(t)
    console.print(
        Text(
            "error = median |predicted - actual| rise in % between two readings. Each window "
            "is predicted only from windows that ended before it began.",
            style="dim",
        )
    )
