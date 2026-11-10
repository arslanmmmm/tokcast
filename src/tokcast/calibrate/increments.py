"""Two ways to learn k, the % of a usage limit per million weighted tokens (milestone 10a).

- **Totals** (the original, mapping.fit): each reading gives `% used ÷ weighted tokens in
  the window so far`; k is their median. Usage outside this machine's logs (claude.ai,
  other devices) inflates every reading taken after it.
- **Increments** (the candidate): consecutive readings of one window give `Δ% ÷ Δtokens`.
  Outside usage before a pair cancels out; outside usage *between* a pair makes that pair
  an outlier, which is detectable because it can only add %, never remove it.

Pure functions over plain records, so every number can be checked by hand. Which one the
product uses is decided by the pre-registered backtest (docs/plan.md, milestone 10a).
"""

from dataclasses import dataclass
from datetime import datetime
from itertools import groupby, pairwise

import numpy as np

MIN_PCT = 2.0  # under this, the 1-point rounding of a reading dominates a ratio
OUTLIER_FACTOR = 3.0  # a pair over 3x the median pair ratio had usage from elsewhere
QUANTILES = (0.1, 0.9)  # the 80% interval


@dataclass(frozen=True)
class Point:
    """One usage reading, with this machine's weighted tokens in its window up to then."""

    resets_at: datetime  # identifies the window
    ts: datetime
    used_pct: float
    weighted: float


@dataclass(frozen=True)
class Pair:
    resets_at: datetime
    ts: datetime  # time of the later reading
    d_pct: float
    d_tokens: float

    @property
    def ratio(self) -> float:
        return self.d_pct / (self.d_tokens / 1e6)


@dataclass(frozen=True)
class Fit:
    k: float  # % per million weighted tokens
    low: float  # 80% interval of k
    high: float
    n: int  # readings (totals) or pairs (increments) used
    flagged: int = 0  # increments only: pairs left out as outside usage


def pairs(points: list[Point]) -> list[Pair]:
    """Consecutive readings of the same window. Pairs with no local tokens are dropped."""
    ordered = sorted(points, key=lambda p: (p.resets_at, p.ts))
    found = []
    for resets_at, group in groupby(ordered, key=lambda p: p.resets_at):
        window = list(group)
        for before, after in pairwise(window):
            d_tokens = after.weighted - before.weighted
            if d_tokens > 0:
                found.append(Pair(resets_at, after.ts, after.used_pct - before.used_pct, d_tokens))
    return found


def _interval(ratios: list[float], fallback: float) -> tuple[float, float]:
    if not ratios:
        return fallback, fallback
    low, high = np.quantile(ratios, QUANTILES)
    return float(low), float(high)


def fit_increments(found: list[Pair]) -> Fit | None:
    """k = ΣΔ% ÷ ΣΔtokens over pairs, leaving out pairs that show outside usage."""
    if not found:
        return None
    typical = float(np.median([p.ratio for p in found]))
    kept = [p for p in found if typical == 0 or p.ratio <= OUTLIER_FACTOR * typical]
    tokens = sum(p.d_tokens for p in kept)
    if not kept or tokens <= 0:
        return None
    k = sum(p.d_pct for p in kept) / (tokens / 1e6)
    low, high = _interval([p.ratio for p in kept if p.d_pct >= MIN_PCT], k)
    return Fit(k, low, high, n=len(kept), flagged=len(found) - len(kept))


def fit_totals(points: list[Point]) -> Fit | None:
    """The original estimator: median of `% used ÷ weighted tokens so far`."""
    ratios = [
        p.used_pct / (p.weighted / 1e6) for p in points if p.used_pct >= MIN_PCT and p.weighted
    ]
    if not ratios:
        return None
    k = float(np.median(ratios))
    low, high = _interval(ratios, k)
    return Fit(k, low, high, n=len(ratios))
