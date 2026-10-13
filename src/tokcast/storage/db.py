"""DuckDB connection and schema setup.

DuckDB is an embedded analytical database: a single local file, no server, and fast
SQL over columns. That fits a privacy-first CLI that mostly runs aggregations.
"""

from importlib.resources import files
from pathlib import Path

import duckdb


def load_sql(name: str) -> str:
    """Read a .sql file shipped inside the package (tokcast/storage/sql/)."""
    return files("tokcast.storage").joinpath("sql", name).read_text(encoding="utf-8")


def connect(path: Path | str) -> duckdb.DuckDBPyConnection:
    """Open (or create) the database and make sure the schema and views exist."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(load_sql("schema.sql"))
    con.execute(load_sql("views.sql"))
    return con
