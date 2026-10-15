"""Load usage-limit readings into the database.

Readings come from the status line (appended to a JSONL file by tokcast/capture.py) or
from `tokcast calibrate --used`. Loading is idempotent: a reading seen again keeps its
earliest time, the moment that percentage was first reached.
"""

import json
from datetime import datetime
from pathlib import Path

import duckdb

from tokcast.capture import SNAPSHOT_FILE, Snapshot


def save(con: duckdb.DuckDBPyConnection, snapshots: list[Snapshot]) -> None:
    """Insert readings; one already known keeps its earliest time."""
    for s in snapshots:
        con.execute(
            """INSERT INTO usage_snapshots VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT ("window", resets_at, used_pct) DO UPDATE SET
                   ts = least(usage_snapshots.ts, excluded.ts)""",
            [s.window, s.resets_at, s.used_pct, s.ts, s.source, s.session_id],
        )


def load_file(con: duckdb.DuckDBPyConnection, data_dir: Path) -> int:
    """Load the status-line JSONL into the database. Bad lines are skipped. Idempotent."""
    path = data_dir / SNAPSHOT_FILE
    if not path.exists():
        return 0
    snapshots = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            raw = json.loads(line)
            snapshots.append(
                Snapshot(
                    window=raw["window"],
                    resets_at=datetime.fromisoformat(raw["resets_at"]),
                    used_pct=float(raw["used_pct"]),
                    ts=datetime.fromisoformat(raw["ts"]),
                    source=raw.get("source", "statusline"),
                    session_id=raw.get("session_id"),
                )
            )
        except (ValueError, KeyError, TypeError):
            continue  # a half-written line (e.g. two sessions writing at once)
    save(con, snapshots)
    return len(snapshots)
