"""Shared helpers for terminal output: token formatting, tables, bars, times."""

from datetime import UTC, datetime

from rich.table import Table


def fmt_tokens(n: float | int | None) -> str:
    """1234 -> '1.2k', 3_400_000 -> '3.4M'. Token counts are easier to scan this way."""
    if n is None:
        return "-"
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= limit:
            value = n / limit
            return f"{value:.1f}{suffix}" if value < 100 else f"{value:.0f}{suffix}"
    return f"{n:.0f}"


def bar(value: float, maximum: float, width: int = 16) -> str:
    if not maximum:
        return ""
    return "█" * max(1, round(width * value / maximum)) if value else ""


def make_table(title: str, *columns: str, right: tuple[str, ...] = ()) -> Table:
    table = Table(title=title, title_justify="left", title_style="bold", box=None, pad_edge=False)
    for col in columns:
        table.add_column(col, justify="right" if col in right else "left", no_wrap=True)
    return table


def pct_range(p: tuple[float, float, float] | None) -> str:
    if not p:
        return "-"
    low, _, high = p
    return f"~{low:.1f}–{high:.1f}%" if high < 10 else f"~{low:.0f}–{high:.0f}%"  # noqa: RUF001


def to_local(dt: datetime) -> datetime:
    """Naive UTC -> local time, for display."""
    return dt.replace(tzinfo=UTC).astimezone()
