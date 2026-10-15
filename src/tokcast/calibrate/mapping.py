"""Learn the user's own mapping from tokens to "% of usage limit".

Anthropic doesn't publish how limits count tokens, so tokcast learns one number per
window from real readings:

    % used  ≈  k x weighted tokens in the window

Weighted tokens ("cost units", see views.sql) weigh each token type by its API price
ratio. Each reading gives one estimate of k (% used / weighted tokens); the median across
readings is the calibration and their spread its uncertainty.

Known bias: usage outside this machine's Claude Code logs (claude.ai, other computers)
counts toward the limit but not toward the weighted tokens here. That makes k too large,
so percentages err on the cautious side (too high, not too low).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import duckdb
import numpy as np

from tokcast.storage.db import load_sql

MIN_POINTS = 3  # readings needed before predictions show percentages
MIN_PCT = 2.0  # below this, rounding of the % reading dominates the ratio
WINDOW_LENGTH = {"5h": timedelta(hours=5), "7d": timedelta(days=7)}


@dataclass
class Calibration:
    window: str
    points: list[dict] = field(default_factory=list)  # readings used, with their ratio
    skipped: int = 0  # readings not usable (too small, or not ingested yet)
    k_low: float | None = None  # % per million weighted tokens: P10 / median / P90
    k: float | None = None
    k_high: float | None = None
    turn_weight: float | None = None  # typical weighted / total tokens of a turn

    @property
    def ready(self) -> bool:
        return len(self.points) >= MIN_POINTS and self.k is not None

    def pct_of_limit(self, total_tokens: float) -> float | None:
        """% of the window a turn with this many tokens processed would use (median k)."""
        if not self.ready or not self.turn_weight:
            return None
        return self.k * self.turn_weight * total_tokens / 1e6


def fit(con: duckdb.DuckDBPyConnection, window: str = "5h") -> Calibration:
    rows = con.execute(load_sql("calibrate/points.sql"), {"window": window}).fetchall()
    total_rows = con.execute(
        'SELECT count(*) FROM usage_snapshots WHERE "window" = ?', [window]
    ).fetchone()[0]
    cal = Calibration(window)
    ratios = []
    for _window, resets_at, used_pct, ts, source, weighted in rows:
        if used_pct < MIN_PCT or not weighted:
            continue
        ratio = used_pct / (weighted / 1e6)
        ratios.append(ratio)
        cal.points.append(
            {
                "ts": ts,
                "resets_at": resets_at,
                "used_pct": used_pct,
                "weighted_tokens": weighted,
                "pct_per_million": ratio,
                "source": source,
            }
        )
    cal.skipped = total_rows - len(cal.points)
    if ratios:
        cal.k_low, cal.k, cal.k_high = (float(v) for v in np.quantile(ratios, [0.1, 0.5, 0.9]))
    row = con.execute(
        "SELECT median(weighted_tokens / total_tokens) FROM turns WHERE total_tokens > 0"
    ).fetchone()
    cal.turn_weight = float(row[0]) if row and row[0] is not None else None
    return cal


def infer_window_end(con: duckdb.DuckDBPyConnection, at: datetime) -> datetime | None:
    """When the 5-hour window containing ``at`` resets, judged from this machine's calls.

    A window starts with the first call after the previous one ended and lasts 5 hours.
    Used for a manual reading when the user doesn't say when the window resets. Usage on
    other devices can start a window earlier than the logs show; --resets-in is safer.
    """
    rows = con.execute("SELECT ts FROM requests WHERE ts <= ? ORDER BY ts", [at]).fetchall()
    times = [t for (t,) in rows]
    if not times:
        return None
    length = WINDOW_LENGTH["5h"]
    start = times[0]
    for t in times:
        if t >= start + length:
            start = t
    end = start + length
    return end if end > at else None


@dataclass(frozen=True)
class Reading:
    window: str
    used_pct: float
    resets_at: datetime
    ts: datetime
    source: str


def latest_reading(con: duckdb.DuckDBPyConnection, window: str, now: datetime) -> Reading | None:
    """The newest reading of a window that hasn't reset yet."""
    row = con.execute(load_sql("calibrate/latest.sql"), {"window": window, "now": now}).fetchone()
    return Reading(window, *row) if row else None
