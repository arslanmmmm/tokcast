"""What the user reads: the text outputs nothing else checks (recorded Rich console)."""

from datetime import datetime, timedelta

import pandas as pd
from rich.console import Console

from tokcast import calibrate as cal
from tokcast import render
from tokcast.evaluate.limits import LimitBacktest
from tokcast.predict import forecast


def printed(draw, *args) -> str:
    console = Console(record=True, width=160, color_system=None)
    draw(*args, console)
    return console.export_text()


def reading_point(k):
    return {
        "ts": datetime(2026, 11, 1, 10),
        "resets_at": datetime(2026, 11, 1, 14),
        "used_pct": 12.0,
        "weighted_tokens": 1.2e6,
        "pct_per_million": k,
        "source": "statusline",
    }


def calibrated(k=10.0):
    return cal.Calibration(
        "5h", points=[reading_point(k)] * 3, k=k, k_low=k * 0.8, k_high=k * 1.2, turn_weight=0.12
    )


def test_calibration_report_before_and_after_three_readings():
    waiting = printed(render.render_calibration, cal.Calibration("5h", points=[reading_point(9.0)]))
    ready = printed(render.render_calibration, calibrated(10.0))

    assert "1 of 3 readings" in waiting
    assert "1% of your 5-hour limit ≈ 100k weighted tokens" in ready  # 1e6 / 10


def test_limit_backtest_table_shows_each_verdict():
    common = dict(
        test_pairs=80,
        mae_totals=0.73,
        mae_increments=0.61,
        diff_low=0.01,
        diff_high=0.15,
        coverage=0.56,
        rel_totals=0.48,
        rel_increments=0.44,
    )
    results = [
        LimitBacktest("5h", test_windows=11, adopt=False, **common),
        LimitBacktest("7d", 0, 0, None, None, None, None, None, None, None, None),
    ]

    text = printed(render.render_limit_backtest, results)

    assert "keep totals" in text and "no decision" in text
    assert "+0.01 to +0.15 pts" in text and "56%" in text


def test_a_turn_that_would_not_fit_in_whats_left_is_flagged():
    now = cal.Reading("5h", 99.0, datetime.now() + timedelta(hours=2), datetime.now(), "statusline")
    f = forecast(
        pd.DataFrame(),
        "refactor the whole parser",
        model="opus",
        effort="high",
        calibration=calibrated(10.0),
        reading=now,
    )

    text = printed(render.render_forecast, f)

    assert "Now: 99% of your 5h limit used" in text
    assert "Careful:" in text and "wouldn't fit" in text


def test_the_cheaper_next_move_is_listed_with_its_assumptions():
    f = forecast(
        pd.DataFrame(),
        "now fix the failing test",
        model="opus",
        effort="high",
        context_mode="given",
        context_tokens=2_000_000,
        compare=False,
    )

    text = printed(render.render_forecast, f)

    assert "Cheaper next move" in text
    assert "/compact" in text and "/clear" in text
    assert "(assumed)" in text  # the /compact size is an assumption
