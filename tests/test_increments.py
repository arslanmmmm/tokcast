"""Increment-based calibration (milestone 10a): checked by hand on small examples.

Units: % of the limit per million weighted tokens, as in calibrate/mapping.py.
"""

from datetime import datetime, timedelta

import pytest

from tokcast.calibrate.increments import Point, fit_increments, fit_totals, pairs

RESETS = datetime(2026, 11, 1, 14, 0)
T0 = datetime(2026, 11, 1, 9, 30)


def point(minute, pct, weighted_m, resets=RESETS):
    return Point(
        resets_at=resets, ts=T0 + timedelta(minutes=minute), used_pct=pct, weighted=weighted_m * 1e6
    )


def test_pairs_are_consecutive_readings_of_the_same_window():
    other = RESETS + timedelta(hours=5)
    points = [
        point(0, 1, 0.10),
        point(10, 3, 0.35),
        point(20, 3, 0.40),
        point(30, 10, 0.50),
        point(40, 2, 0.20, resets=other),  # another window: never paired across
        point(50, 5, 0.20, resets=other),  # no local tokens in between: dropped
    ]

    got = [(p.d_pct, round(p.d_tokens / 1e6, 2)) for p in pairs(points)]

    assert got == [(2, 0.25), (0, 0.05), (7, 0.10)]


def test_increments_use_a_ratio_of_sums_and_leave_out_outside_usage():
    points = [point(0, 1, 0.10), point(10, 3, 0.35), point(20, 3, 0.40), point(30, 10, 0.50)]
    # pair ratios: 2/0.25 = 8, 0/0.05 = 0, 7/0.10 = 70. Median 8, and 70 > 3 x 8:
    # that jump came from usage elsewhere, so it is left out.

    fit = fit_increments(pairs(points))

    assert fit.k == pytest.approx((2 + 0) / (0.25 + 0.05))  # 6.67 % per M
    assert fit.n == 2 and fit.flagged == 1


def test_increment_interval_uses_pairs_with_at_least_2_points():
    points = [point(0, 0, 0.0), point(10, 2, 0.25), point(20, 5, 0.55), point(30, 9, 1.05)]
    # ratios 8, 10, 8 (all >= 2 points): P10/P90 of [8, 8, 10]

    fit = fit_increments(pairs(points))

    assert fit.low == pytest.approx(8.0)
    assert fit.high == pytest.approx(9.6)
    assert fit.k == pytest.approx(9 / 1.05)


def test_totals_is_the_median_of_cumulative_ratios_from_2_percent():
    points = [point(0, 1, 0.10), point(10, 4, 0.50), point(20, 6, 0.50), point(30, 10, 1.0)]
    # usable (>= 2%): 4/0.5 = 8, 6/0.5 = 12, 10/1.0 = 10 -> median 10

    fit = fit_totals(points)

    assert fit.k == pytest.approx(10.0)
    assert fit.n == 3


def test_no_usable_data_gives_no_fit():
    assert fit_increments([]) is None
    assert fit_totals([point(0, 1, 0.1)]) is None
