"""Capture usage-limit readings from Claude Code's status line. Standard library only.

Claude Code runs the status-line command after every assistant message, with session
data as JSON on stdin. For claude.ai Pro and Max subscribers that includes
`rate_limits.five_hour` and `rate_limits.seven_day`, each with `used_percentage` and
`resets_at` (Unix seconds). See https://code.claude.com/docs/en/statusline.

This runs often, so it must be fast and must never fail:
- it imports nothing heavy (no pandas, no DuckDB): startup stays well under 0.1 s;
- it only appends a line to a small JSONL file, and only when a reading changed.
DuckDB allows one writing process at a time, so it is never opened here; `tokcast ingest`
and `tokcast calibrate` load the file later (see calibrate/snapshots.py).
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SNAPSHOT_FILE = "usage_snapshots.jsonl"
STATE_FILE = "statusline_state.json"
WINDOWS = {"five_hour": "5h", "seven_day": "7d"}


@dataclass(frozen=True)
class Snapshot:
    window: str  # "5h" or "7d"
    resets_at: datetime  # naive UTC
    used_pct: float
    ts: datetime  # naive UTC
    source: str  # "statusline" or "manual"
    session_id: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def from_statusline(data: dict[str, Any], now: datetime) -> list[Snapshot]:
    """Readings in a status-line payload. Every field is optional (see the docs)."""
    limits = data.get("rate_limits")
    if not isinstance(limits, dict):
        return []
    found = []
    for key, window in WINDOWS.items():
        entry = limits.get(key)
        if not isinstance(entry, dict):
            continue
        pct, resets = entry.get("used_percentage"), entry.get("resets_at")
        if isinstance(pct, int | float) and isinstance(resets, int | float):
            resets_at = datetime.fromtimestamp(resets, UTC).replace(tzinfo=None)
            session = data.get("session_id") if isinstance(data.get("session_id"), str) else None
            found.append(Snapshot(window, resets_at, float(pct), now, "statusline", session))
    return found


def record_changed(data_dir: Path, snapshots: list[Snapshot]) -> int:
    """Append readings that differ from the last ones recorded. Returns how many."""
    if not snapshots:
        return 0
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path = data_dir / STATE_FILE
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    new = [s for s in snapshots if state.get(s.window) != [s.resets_at.isoformat(), s.used_pct]]
    if not new:
        return 0
    with (data_dir / SNAPSHOT_FILE).open("a", encoding="utf-8") as fh:
        for s in new:
            fh.write(json.dumps(asdict(s), default=str) + "\n")
    for s in new:
        state[s.window] = [s.resets_at.isoformat(), s.used_pct]
    state_path.write_text(json.dumps(state))
    return len(new)


def statusline_text(data: dict) -> str:
    """One short line for Claude Code's status bar, e.g. '5h 23% (resets 14:30) · ctx 42%'."""
    parts = []
    limits = data.get("rate_limits") or {}
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        entry = limits.get(key) or {}
        pct, resets = entry.get("used_percentage"), entry.get("resets_at")
        if isinstance(pct, int | float):
            when = ""
            if isinstance(resets, int | float):
                fmt = "%H:%M" if key == "five_hour" else "%a %H:%M"
                when = f" (resets {datetime.fromtimestamp(resets).strftime(fmt)})"
            parts.append(f"{label} {pct:.0f}%{when}")
    ctx = (data.get("context_window") or {}).get("used_percentage")
    if isinstance(ctx, int | float):
        parts.append(f"ctx {ctx:.0f}%")
    return "tokcast · " + " · ".join(parts) if parts else "tokcast"


def run(stdin_text: str, data_dir: Path) -> str:
    """The whole status-line command: record readings, return the line to print."""
    try:
        data = json.loads(stdin_text or "{}")
        record_changed(data_dir, from_statusline(data, utcnow()))
        return statusline_text(data)
    except Exception:  # a status line must never break Claude Code's UI
        return "tokcast"
