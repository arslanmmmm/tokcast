"""Build the usage report behind `tokcast stats`.

Each section is one SQL file in ``storage/sql/stats/``. This module only runs them and
returns plain data (lists of dicts), so the same report can be printed as tables,
dumped as JSON, or used by other front ends.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb

from tokcast.storage.db import load_sql

Rows = list[dict[str, Any]]

# Turns that started before this count as "all history" when no --days filter is given.
_BEGINNING = datetime(1970, 1, 1)


@dataclass
class StatsReport:
    since: datetime | None
    overview: dict[str, Any]
    by_model: Rows = field(default_factory=list)
    by_day: Rows = field(default_factory=list)
    by_project: Rows = field(default_factory=list)
    top_sessions: Rows = field(default_factory=list)
    context_cost: Rows = field(default_factory=list)
    turn_length: Rows = field(default_factory=list)
    data_quality: Rows = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.overview.get("turns")

    @property
    def context_cost_ratio(self) -> float | None:
        """How many times more a call in the largest context bucket costs than in the smallest."""
        buckets = [row for row in self.context_cost if row["median_call_tokens"]]
        if len(buckets) < 2:
            return None
        return buckets[-1]["median_call_tokens"] / buckets[0]["median_call_tokens"]


def query(con: duckdb.DuckDBPyConnection, name: str, **params: Any) -> Rows:
    """Run ``stats/<name>.sql`` with named parameters and return rows as dicts."""
    cursor = con.execute(load_sql(f"stats/{name}.sql"), params)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def build_report(
    con: duckdb.DuckDBPyConnection,
    *,
    days: int | None = None,
    top: int = 5,
    now: datetime | None = None,
) -> StatsReport:
    """Collect every section. ``days`` limits the report to recent turns."""
    since = None
    if days is not None:
        now = now or datetime.now(UTC).replace(tzinfo=None)
        since = now - timedelta(days=days)
    s = since or _BEGINNING
    return StatsReport(
        since=since,
        overview=query(con, "overview", since=s)[0],
        by_model=query(con, "by_model", since=s),
        by_day=query(con, "by_day", since=s),
        by_project=query(con, "by_project", since=s),
        top_sessions=query(con, "top_sessions", since=s, top=top),
        context_cost=query(con, "context_cost", since=s),
        turn_length=query(con, "turn_length", since=s),
        data_quality=query(con, "data_quality"),
    )
