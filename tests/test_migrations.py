"""Numbered schema migrations (storage/migrations.py): upgrades are recorded and atomic."""

import duckdb
import pytest

from tokcast.storage import db, migrations

LATEST = migrations.latest()


def versions(con):
    return [v for (v,) in con.execute("SELECT version FROM schema_version ORDER BY 1").fetchall()]


def columns(con, table):
    return {row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()}


def make_old_database(path):
    """A database as tokcast 0.1 left it: no schema_version table, no agent_id column."""
    con = db.connect(path)
    con.execute(
        "INSERT INTO usage_snapshots VALUES "
        "('5h', '2026-10-01 14:00', 5, '2026-10-01 10:00', 'manual', NULL)"
    )
    con.execute("DROP VIEW IF EXISTS turns; DROP VIEW IF EXISTS v_requests")
    con.execute("ALTER TABLE requests DROP COLUMN agent_id")
    con.execute("DROP TABLE schema_version")
    con.close()


def test_a_new_database_is_at_the_latest_version():
    con = db.connect(":memory:")

    assert versions(con) == list(range(1, LATEST + 1))


def test_an_old_database_is_upgraded_and_keeps_its_data(tmp_path):
    path = tmp_path / "old.duckdb"
    make_old_database(path)

    con = db.connect(path)

    assert "agent_id" in columns(con, "requests")
    assert versions(con) == list(range(1, LATEST + 1))
    assert con.execute("SELECT count(*) FROM usage_snapshots").fetchone()[0] == 1


def test_migrations_run_once(tmp_path):
    path = tmp_path / "t.duckdb"
    db.connect(path).close()

    con = db.connect(path)

    assert versions(con) == list(range(1, LATEST + 1))  # no duplicate rows


def test_a_failing_migration_leaves_nothing_half_done(tmp_path, monkeypatch):
    path = tmp_path / "t.duckdb"
    db.connect(path).close()
    broken = migrations.Migration(
        LATEST + 1, "broken", "CREATE TABLE half_done (x INTEGER); SELECT * FROM no_such_table;"
    )
    monkeypatch.setattr(
        migrations, "all_migrations", lambda: [*migrations.all_migrations_on_disk(), broken]
    )

    with pytest.raises(duckdb.Error):
        db.connect(path)

    con = duckdb.connect(str(path))
    assert max(versions(con)) == LATEST  # not recorded
    tables = {
        t for (t,) in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    assert "half_done" not in tables  # and rolled back


def test_a_database_from_a_newer_tokcast_is_refused(tmp_path):
    path = tmp_path / "t.duckdb"
    con = db.connect(path)
    con.execute("INSERT INTO schema_version VALUES (?, 'from the future', now())", [LATEST + 1])
    con.close()

    with pytest.raises(migrations.DatabaseTooNew, match="newer tokcast"):
        db.connect(path)
