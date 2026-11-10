"""Numbered schema migrations, recorded in a ``schema_version`` table.

``schema.sql`` is the baseline and isn't edited for changes any more. Each change is a
new file ``sql/migrations/NNN_name.sql``; ``migrate`` runs the ones a database hasn't had
yet, in order, each in its own transaction together with its version row, so an upgrade
either completes or leaves nothing behind. A database written by a newer tokcast is
refused instead of misread.
"""

import re
from dataclasses import dataclass
from importlib.resources import files

import duckdb

_FILE = re.compile(r"(\d{3})_(\w+)\.sql")


class DatabaseTooNew(Exception):
    """The database has migrations this tokcast doesn't know: it came from a newer one."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def all_migrations_on_disk() -> list[Migration]:
    folder = files("tokcast.storage").joinpath("sql", "migrations")
    found = []
    for item in folder.iterdir():
        if match := _FILE.fullmatch(item.name):
            sql = item.read_text(encoding="utf-8")
            found.append(Migration(int(match[1]), match[2], sql))
    return sorted(found, key=lambda m: m.version)


def all_migrations() -> list[Migration]:
    """The migrations this tokcast ships (a seam for tests)."""
    return all_migrations_on_disk()


def latest() -> int:
    return max((m.version for m in all_migrations()), default=0)


def current(con: duckdb.DuckDBPyConnection) -> int:
    (version,) = con.execute("SELECT coalesce(max(version), 0) FROM schema_version").fetchone() or (
        0,
    )
    return int(version)


def migrate(con: duckdb.DuckDBPyConnection) -> list[int]:
    """Apply the migrations the database hasn't had. Returns the versions applied."""
    con.execute(
        """CREATE TABLE IF NOT EXISTS schema_version (
               version    INTEGER PRIMARY KEY,
               name       VARCHAR NOT NULL,
               applied_at TIMESTAMP NOT NULL
           )"""
    )
    have, known = current(con), all_migrations()
    newest = max((m.version for m in known), default=0)
    if have > newest:
        raise DatabaseTooNew(
            f"This database was written by a newer tokcast (schema version {have}; this "
            f"tokcast knows up to {newest}). Upgrade tokcast to use it."
        )
    applied = []
    for migration in known:
        if migration.version <= have:
            continue
        con.begin()
        try:
            con.execute(migration.sql)
            con.execute(
                "INSERT INTO schema_version VALUES (?, ?, now())",
                [migration.version, migration.name],
            )
            con.commit()
        except duckdb.Error:
            con.rollback()
            raise
        applied.append(migration.version)
    return applied
