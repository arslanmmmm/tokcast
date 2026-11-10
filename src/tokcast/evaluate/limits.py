"""Forward backtest of the "% of usage limit" calibration: totals vs increments.

Implements the rule pre-registered in docs/plan.md (milestone 10a) before any results:
windows are ordered in time, each one is predicted only from windows that *ended before
it began*, and the candidate is adopted only if a window-block bootstrap interval of the
improvement is entirely above zero and its 80% interval covers enough held-out pairs.
"""

from dataclasses import dataclass
from datetime import datetime
from itertools import groupby

import duckdb
import numpy as np

from tokcast.calibrate.increments import Fit, Point, fit_increments, fit_totals, pairs
from tokcast.storage.db import load_sql

MIN_TRAIN_WINDOWS = {"5h": 3, "7d": 2}
MIN_COVERAGE = 0.65  # of the increments' 80% interval on held-out pairs
DRAWS = 2000
SEED = 10


@dataclass(frozen=True)
class Window:
    resets_at: datetime
    first: datetime
    last: datetime
    points: tuple[Point, ...]


@dataclass(frozen=True)
class PairResult:
    resets_at: datetime
    actual: float  # Δ% in percentage points
    totals: float  # predicted Δ% by each estimator
    increments: float
    inside: bool  # actual within the increments' 80% interval


@dataclass(frozen=True)
class LimitBacktest:
    window: str
    test_windows: int
    test_pairs: int
    mae_totals: float | None  # median absolute error, percentage points
    mae_increments: float | None
    diff_low: float | None  # 95% interval of mae_totals - mae_increments
    diff_high: float | None
    coverage: float | None
    rel_totals: float | None  # secondary: median |error| / actual, for actual > 0
    rel_increments: float | None
    adopt: bool | None  # None: not enough data for a decision


def load_points(con: duckdb.DuckDBPyConnection, window: str) -> list[Point]:
    """Readings of one window type with their weighted tokens (calibrate/points.sql)."""
    rows = con.execute(load_sql("calibrate/points.sql"), {"window": window}).fetchall()
    return [Point(resets, ts, float(pct), float(w)) for _, resets, pct, ts, _, w in rows]


def windows_in_order(points: list[Point]) -> list[Window]:
    ordered = sorted(points, key=lambda p: (p.resets_at, p.ts))
    found = []
    for resets_at, group in groupby(ordered, key=lambda p: p.resets_at):
        window = tuple(group)
        found.append(Window(resets_at, window[0].ts, window[-1].ts, window))
    return sorted(found, key=lambda w: w.first)


def _predict(test: Window, totals: Fit, inc: Fit) -> list[PairResult]:
    results = []
    for pair in pairs(list(test.points)):
        m = pair.d_tokens / 1e6
        results.append(
            PairResult(
                resets_at=test.resets_at,
                actual=pair.d_pct,
                totals=totals.k * m,
                increments=inc.k * m,
                inside=inc.low * m <= pair.d_pct <= inc.high * m,
            )
        )
    return results


def held_out(points: list[Point], window: str) -> list[PairResult]:
    """Every test pair, predicted from the windows that ended before its own began."""
    order = windows_in_order(points)
    min_train = MIN_TRAIN_WINDOWS[window]
    results = []
    for test in order:
        train = [w for w in order if w.last < test.first]
        if len(train) < min_train:
            continue
        points = [p for w in train for p in w.points]
        totals, inc = fit_totals(points), fit_increments(pairs(points))
        if totals is not None and inc is not None:
            results.extend(_predict(test, totals, inc))
    return results


def _mae(results: list[PairResult], method: str) -> float:
    return float(np.median([abs(getattr(r, method) - r.actual) for r in results]))


def _relative(results: list[PairResult], method: str) -> float | None:
    rel = [abs(getattr(r, method) - r.actual) / r.actual for r in results if r.actual > 0]
    return float(np.median(rel)) if rel else None


def _bootstrap_diff(results: list[PairResult]) -> tuple[float, float]:
    """95% interval of mae_totals - mae_increments, resampling whole test windows."""
    by_window = [list(g) for _, g in groupby(results, key=lambda r: r.resets_at)]
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(DRAWS):
        drawn = [r for i in rng.integers(len(by_window), size=len(by_window)) for r in by_window[i]]
        diffs.append(_mae(drawn, "totals") - _mae(drawn, "increments"))
    low, high = np.quantile(diffs, (0.025, 0.975))
    return float(low), float(high)


def backtest(points: list[Point], window: str) -> LimitBacktest:
    results = held_out(points, window)
    if not results:
        return LimitBacktest(window, 0, 0, None, None, None, None, None, None, None, None)
    diff_low, diff_high = _bootstrap_diff(results)
    coverage = float(np.mean([r.inside for r in results]))
    return LimitBacktest(
        window=window,
        test_windows=len({r.resets_at for r in results}),
        test_pairs=len(results),
        mae_totals=_mae(results, "totals"),
        mae_increments=_mae(results, "increments"),
        diff_low=diff_low,
        diff_high=diff_high,
        coverage=coverage,
        rel_totals=_relative(results, "totals"),
        rel_increments=_relative(results, "increments"),
        adopt=diff_low > 0 and coverage >= MIN_COVERAGE,
    )
