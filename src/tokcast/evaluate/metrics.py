"""Scores for range forecasts. Pure functions on arrays, so each is easy to check by hand.

Token counts span orders of magnitude, so errors are measured as *ratios* (on a log
scale): predicting 200k for a 100k turn is as wrong as predicting 50k.
"""

from dataclasses import dataclass

import numpy as np

QUANTILES = (0.1, 0.5, 0.9)


@dataclass(frozen=True)
class Scores:
    n: int
    coverage: float  # share of actual values inside [low, high]; target 0.8
    coverage_margin: float  # +- 95% margin of error of that share (normal approximation)
    below: float  # share below the range (forecast too high)
    above: float  # share above the range (forecast too low)
    within_2x: float  # share where the median is within a factor 2 of the actual value
    median_error: float  # median |median - actual| / actual
    bias: float  # typical median / actual; 1.0 = unbiased, 2.0 = twice too high
    width: float  # typical high / low ratio; smaller = sharper (if coverage holds)
    pinball: float  # mean quantile loss on log scale over P10/P50/P90; lower is better


def score(actual, low, median, high) -> Scores:
    """Score forecasts ``low``/``median``/``high`` (P10/P50/P90) against ``actual``."""
    a, lo, me, hi = (
        np.maximum(np.asarray(x, dtype=float), 1.0) for x in (actual, low, median, high)
    )
    n = len(a)
    inside = (lo <= a) & (a <= hi)
    coverage = float(inside.mean())
    log_ratio = np.log(me) - np.log(a)
    return Scores(
        n=n,
        coverage=coverage,
        coverage_margin=float(1.96 * np.sqrt(coverage * (1 - coverage) / n)),
        below=float((a < lo).mean()),
        above=float((a > hi).mean()),
        within_2x=float((np.abs(log_ratio) <= np.log(2)).mean()),
        median_error=float(np.median(np.abs(me - a) / a)),
        bias=float(np.exp(np.median(log_ratio))),
        width=float(np.exp(np.median(np.log(hi) - np.log(lo)))),
        pinball=pinball_loss(np.log(a), [np.log(lo), np.log(me), np.log(hi)]),
    )


def pinball_loss(actual, predictions, quantiles=QUANTILES) -> float:
    """Average quantile ("pinball") loss. For quantile q, under-predicting costs q per unit
    and over-predicting costs (1 - q): a P90 forecast is punished mostly for being too low,
    a P10 mostly for being too high. It rewards ranges that are both right and narrow."""
    y = np.asarray(actual, dtype=float)
    losses = []
    for q, pred in zip(quantiles, predictions, strict=True):
        diff = y - np.asarray(pred, dtype=float)
        losses.append(np.maximum(q * diff, (q - 1) * diff).mean())
    return float(np.mean(losses))


def pinball_per_turn(actual, predictions) -> np.ndarray:
    """Pinball loss of each turn (averaged over P10/P50/P90), on a log scale.

    ``predictions`` has one row per turn and the columns low, median, high."""
    y = np.log(np.maximum(np.asarray(actual, dtype=float), 1.0))
    p = np.log(np.maximum(np.asarray(predictions, dtype=float), 1.0))
    q = np.asarray(QUANTILES)
    diff = y[:, None] - p
    return np.maximum(q * diff, (q - 1) * diff).mean(axis=1)


def paired_difference(a, b) -> tuple[float, float, float]:
    """Mean of (a - b) over the same turns, with a 95% interval (normal approximation).

    Comparing two methods on the *same* turns cancels out how hard each turn is, so
    this detects much smaller real differences than comparing two averages would.
    Turns of one session aren't fully independent, so read the interval as optimistic.
    """
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    mean = float(d.mean())
    half = float(1.96 * d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else float("inf")
    return mean, mean - half, mean + half
