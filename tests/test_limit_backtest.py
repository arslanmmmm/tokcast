"""Forward backtest of the % calibration (milestone 10a), on windows with a known true k."""

from datetime import datetime, timedelta
from itertools import pairwise

from tokcast.calibrate.increments import Point
from tokcast.evaluate.limits import backtest, held_out, windows_in_order

START = datetime(2026, 11, 1, 8, 0)
K = 10.0  # true % per million weighted tokens


def window(day, outside_pct=0.0, steps=6):
    """One 5h window: 0.2M local tokens per step at k = 10, after `outside_pct` of usage
    from claude.ai at its start (which no local log can see)."""
    resets = START + timedelta(days=day, hours=5)
    points = []
    for step in range(1, steps + 1):
        tokens = 0.2e6 * step
        points.append(
            Point(
                resets_at=resets,
                ts=START + timedelta(days=day, minutes=20 * step),
                used_pct=outside_pct + K * tokens / 1e6,
                weighted=tokens,
            )
        )
    return points


def test_each_window_is_predicted_only_from_windows_that_ended_before_it():
    points = [p for day in range(5) for p in window(day)]

    order = windows_in_order(points)

    assert len(order) == 5
    assert all(a.last < b.first for a, b in pairwise(order))


def test_outside_usage_makes_totals_worse_and_increments_are_adopted():
    # Every window starts with 20% used on claude.ai: totals can't tell it apart.
    points = [p for day in range(8) for p in window(day, outside_pct=20)]

    result = backtest(points, "5h")

    assert result.test_windows == 5  # 8 windows, the first 3 only train
    assert result.mae_increments < 1e-9  # Δ% / Δtokens recovers k exactly
    assert result.mae_totals > 1
    assert result.diff_low > 0
    assert result.coverage >= 0.65
    assert result.adopt is True


def test_without_outside_usage_there_is_no_reason_to_switch():
    points = [p for day in range(8) for p in window(day)]

    result = backtest(points, "5h")

    assert result.adopt is False  # both exact: the difference interval isn't above 0


def test_too_few_windows_is_no_decision():
    points = [p for day in range(3) for p in window(day)]

    result = backtest(points, "5h")

    assert result.test_windows == 0
    assert result.adopt is None


def test_a_later_window_never_leaks_into_an_earlier_prediction():
    honest = [p for day in range(4) for p in window(day, outside_pct=20)]
    # Day 9 has 10x the usage per token. If it leaked into day 3's training data,
    # day 3's predictions (the only test window here) would change.
    future = [
        Point(p.resets_at, p.ts, p.used_pct * 10, p.weighted) for p in window(9, outside_pct=20)
    ]

    day3 = honest[-1].resets_at

    alone = held_out(honest, "5h")
    with_future = [r for r in held_out(honest + future, "5h") if r.resets_at == day3]

    assert alone and with_future == alone  # day 3's predictions are untouched
