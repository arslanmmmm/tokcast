"""Filesystem locations used by tokcast.

Everything lives on the local disk. Two environment variables override the defaults,
which keeps tests and demos isolated from the user's real data:

- ``TOKCAST_HOME``: where tokcast keeps its own DuckDB database.
- ``TOKCAST_LOGS``: where Claude Code session logs are read from.
"""

import os
from pathlib import Path

DB_FILENAME = "tokcast.duckdb"


def data_dir() -> Path:
    """Directory for tokcast's own data (follows the XDG convention by default)."""
    if env := os.environ.get("TOKCAST_HOME"):
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME", "~/.local/share")
    return Path(xdg).expanduser() / "tokcast"


def db_path() -> Path:
    return data_dir() / DB_FILENAME


def claude_logs_dir() -> Path:
    """Where Claude Code writes one JSONL file per session, grouped by project."""
    if env := os.environ.get("TOKCAST_LOGS"):
        return Path(env).expanduser()
    return Path("~/.claude/projects").expanduser()
