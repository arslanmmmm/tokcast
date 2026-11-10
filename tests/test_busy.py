"""DuckDB allows one writing process. A busy database is waited for, then explained."""

import subprocess
import sys
import time

import pytest
from typer.testing import CliRunner

from tokcast.cli import app
from tokcast.storage import db

HOLD = (
    "import duckdb, sys, time; c = duckdb.connect(sys.argv[1]); "
    "print('locked', flush=True); time.sleep(float(sys.argv[2]))"
)


def hold_lock(path, seconds):
    """Another process (like a running ingest) holding the database's write lock."""
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLD, str(path), str(seconds)], stdout=subprocess.PIPE, text=True
    )
    assert proc.stdout.readline().strip() == "locked"
    return proc


def test_waits_for_a_short_lock(tmp_path):
    path = tmp_path / "t.duckdb"
    holder = hold_lock(path, 1.0)
    start = time.monotonic()

    db.connect(path, busy_wait=10).close()

    assert time.monotonic() - start >= 0.5  # it waited instead of failing
    holder.wait()


def test_gives_up_with_a_clear_error(tmp_path):
    path = tmp_path / "t.duckdb"
    holder = hold_lock(path, 5.0)
    try:
        with pytest.raises(db.DatabaseBusy, match="in use by another tokcast process"):
            db.connect(path, busy_wait=0.5)
    finally:
        holder.kill()
        holder.wait()


def test_cli_prints_one_line_instead_of_a_traceback(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("TOKCAST_HOME", str(home))
    monkeypatch.setenv("TOKCAST_LOGS", str(tmp_path / "no-logs"))
    home.mkdir()
    (home / "tokcast.duckdb").touch()  # a database exists, so stats tries to open it

    def busy(*args, **kwargs):
        raise db.DatabaseBusy("The tokcast database is in use by another tokcast process.")

    monkeypatch.setattr(db, "connect", busy)
    result = CliRunner().invoke(app, ["stats"])

    assert result.exit_code == 3
    assert "in use by another tokcast process" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
