"""Terminal output (Rich). Turns report data into tables; contains no analysis logic.

One module per command; this package re-exports what the CLI uses."""

from tokcast.render.calibrate import render_calibration, render_statusline_setup
from tokcast.render.common import fmt_tokens
from tokcast.render.evaluate import backtest_markdown, render_backtest, render_limit_backtest
from tokcast.render.forecast import render_forecast
from tokcast.render.stats import render_stats

__all__ = [
    "backtest_markdown",
    "fmt_tokens",
    "render_backtest",
    "render_calibration",
    "render_forecast",
    "render_limit_backtest",
    "render_stats",
    "render_statusline_setup",
]
