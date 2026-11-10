"""DuckDB connection and schema setup.

DuckDB is an embedded analytical database: a single local file, no server, and fast
SQL over columns. That fits a privacy-first CLI that mostly runs aggregations.
"""

import time
from importlib.resources import files
from pathlib import Path

import duckdb

from tokcast import config, private

# DuckDB downloads missing extensions from the internet on demand; tokcast is local-only.
OFFLINE = {"autoinstall_known_extensions": False, "autoload_known_extensions": False}

# DuckDB allows one writing process. An incremental ingest takes ~2 s, so wait a little
# for the lock before giving up.
BUSY_WAIT_SECONDS = 10.0
RETRY_SECONDS = 0.25


class DatabaseBusy(Exception):
    """Another process holds the database's write lock for longer than we waited."""


def _open(path: str, busy_wait: float) -> duckdb.DuckDBPyConnection:
    deadline = time.monotonic() + busy_wait
    while True:
        try:
            return duckdb.connect(path, config=OFFLINE)
        except duckdb.IOException as error:
            if "Could not set lock" not in str(error):
                raise
            if time.monotonic() >= deadline:
                raise DatabaseBusy(
                    "The tokcast database is in use by another tokcast process "
                    f"(for example an ingest); waited {busy_wait:g} s. Try again in a moment."
                ) from error
            time.sleep(RETRY_SECONDS)


def load_sql(name: str) -> str:
    """Read a .sql file shipped in the package, e.g. ``"schema.sql"``, ``"stats/by_day.sql"``."""
    return files("tokcast.storage").joinpath("sql", *name.split("/")).read_text(encoding="utf-8")


def connect(path: Path | str, *, busy_wait: float = BUSY_WAIT_SECONDS) -> duckdb.DuckDBPyConnection:
    """Open (or create) the database and make sure the schema and views exist.

    Raises DatabaseBusy when another process keeps the write lock for ``busy_wait`` s.
    """
    on_disk = str(path) != ":memory:"
    if on_disk:
        private.ensure_dir(Path(path).parent, tighten_existing=config.uses_default_data_dir())
    con = _open(str(path), busy_wait)
    if on_disk:  # the file holds prompt text: owner-only, also for databases made by 0.1
        private.protect(Path(path), Path(f"{path}.wal"))
    con.execute(load_sql("schema.sql"))
    con.execute(load_sql("views.sql"))
    return con
