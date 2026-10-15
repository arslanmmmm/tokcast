"""Calibration: usage-limit readings -> "% of limit" for predicted turns.

Weighted tokens of the fixture session s1 (window 2026-10-01 09:00-14:00 UTC), by hand:
  r1  3 + 500 x 2 (1h cache write) + 1000 x 0.1 + 120 x 5    = 1703
  r2  1 + 50 x 1.25                + 1500 x 0.1 + 60 x 5     = 513.5
  r4  2 + 200 x 1.25               + 3000 x 0.1 + 40 x 5     = 752
  ra1 5 + 800 x 1.25               + 0          + 30 x 5     = 1155   (subagent)
  ra2 2 + 100 x 1.25               + 800 x 0.1  + 20 x 5     = 307    (subagent)
  total 4430.5
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta

import pandas as pd
import pytest
from typer.testing import CliRunner

from tokcast import calibrate as cal
from tokcast import capture
from tokcast.cli import app
from tokcast.ingest import pipeline
from tokcast.ingest.sources import ClaudeCodeSource
from tokcast.predict import forecast

runner = CliRunner()
S1_WEIGHTED = 4430.5
RESETS = datetime(2026, 10, 1, 14, 0)  # the 5-hour window 09:00-14:00 UTC


def reading(pct, minute, resets=RESETS, source="manual"):
    return cal.Snapshot("5h", resets, pct, datetime(2026, 10, 1, 10, minute, 30), source)


@pytest.fixture
def loaded(con, logs_dir):
    pipeline.ingest(con, ClaudeCodeSource(), logs_dir)
    return con


# -- capture (status line) -----------------------------------------------------------------


PAYLOAD = {
    "session_id": "abc",
    "rate_limits": {
        "five_hour": {"used_percentage": 23.5, "resets_at": 1_791_400_000},
        "seven_day": {"used_percentage": 41.2, "resets_at": 1_791_900_000},
    },
    "context_window": {"used_percentage": 42},
}


def test_statusline_payload_to_snapshots():
    now = datetime(2026, 10, 15, 3, 0)
    five, seven = capture.from_statusline(PAYLOAD, now)
    assert (five.window, five.used_pct, five.session_id, five.ts) == ("5h", 23.5, "abc", now)
    assert five.resets_at == datetime(2026, 10, 7, 19, 6, 40)  # 1_791_400_000 in UTC
    assert seven.window == "7d"
    # Every field is optional: free plans have no rate_limits at all.
    assert capture.from_statusline({}, now) == []
    assert (
        capture.from_statusline({"rate_limits": {"five_hour": {"used_percentage": "x"}}}, now) == []
    )


def test_only_changed_readings_are_appended(tmp_path):
    now = datetime(2026, 10, 15, 3, 0)
    snaps = capture.from_statusline(PAYLOAD, now)
    assert capture.record_changed(tmp_path, snaps) == 2
    assert capture.record_changed(tmp_path, snaps) == 0  # same readings: nothing written
    PAYLOAD2 = json.loads(json.dumps(PAYLOAD))
    PAYLOAD2["rate_limits"]["five_hour"]["used_percentage"] = 24.0
    assert capture.record_changed(tmp_path, capture.from_statusline(PAYLOAD2, now)) == 1
    assert len((tmp_path / capture.SNAPSHOT_FILE).read_text().splitlines()) == 3


def test_status_line_never_fails(tmp_path):
    assert capture.run("not json", tmp_path) == "tokcast"
    assert capture.run("", tmp_path) == "tokcast"
    text = capture.run(json.dumps(PAYLOAD), tmp_path)
    assert text.startswith("tokcast · 5h 24% (resets ") and text.endswith(" · ctx 42%")


def test_status_line_imports_stay_light():
    # Regression: importing pandas made every status-line run take ~1 s.
    code = "import sys, tokcast.cli, tokcast.capture; print('pandas' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_load_file_is_idempotent_and_keeps_the_earliest_time(con, tmp_path):
    early, late = datetime(2026, 10, 15, 3, 0), datetime(2026, 10, 15, 4, 0)
    path = tmp_path / capture.SNAPSHOT_FILE
    lines = [capture.from_statusline(PAYLOAD, late)[0], capture.from_statusline(PAYLOAD, early)[0]]
    from dataclasses import asdict

    path.write_text("".join(json.dumps(asdict(s), default=str) + "\n" for s in lines) + "{broken\n")
    assert cal.load_file(con, tmp_path) == 2
    cal.load_file(con, tmp_path)
    rows = con.execute("SELECT ts FROM usage_snapshots WHERE \"window\" = '5h'").fetchall()
    assert rows == [(early,)]


# -- mapping ---------------------------------------------------------------------------------


def test_weighted_tokens_by_hand(loaded):
    total = loaded.execute(
        "SELECT sum(weighted_tokens) FROM v_requests WHERE session_id = 's1'"
    ).fetchone()[0]
    assert total == pytest.approx(S1_WEIGHTED)


def test_fit_needs_three_readings_and_uses_the_median(loaded):
    cal.save(loaded, [reading(9.0, 5)])
    one = cal.fit(loaded)
    assert not one.ready
    assert one.points[0]["pct_per_million"] == pytest.approx(9.0 / (S1_WEIGHTED / 1e6))

    cal.save(loaded, [reading(10.0, 5), reading(11.0, 5)])
    three = cal.fit(loaded)
    assert three.ready
    assert three.k == pytest.approx(10.0 / (S1_WEIGHTED / 1e6))  # the middle reading
    assert three.k_low < three.k < three.k_high


def test_unusable_readings_are_skipped(loaded):
    cal.save(loaded, [reading(1.0, 5)])  # under 2%: rounding dominates
    later = cal.Snapshot("5h", RESETS, 30.0, datetime(2026, 10, 1, 12, 0), "manual")
    cal.save(loaded, [later])  # after the last ingested call: tokens not loaded yet
    result = cal.fit(loaded)
    assert (result.points, result.skipped) == ([], 2)


def test_pct_of_limit():
    c = cal.Calibration("5h", points=[{}, {}, {}], k=2.0, k_low=1.0, k_high=3.0, turn_weight=0.5)
    assert c.pct_of_limit(4_000_000) == pytest.approx(2.0 * 0.5 * 4.0)  # % per M x weight x M
    assert cal.Calibration("5h").pct_of_limit(1e6) is None  # not ready


def test_infer_window_end(loaded):
    # Calls start 2025-06-01 09:00 (legacy) and 2026-10-01 10:00: two separate windows.
    end = cal.infer_window_end(loaded, datetime(2026, 10, 1, 11, 0))
    assert end == datetime(2026, 10, 1, 10, 0, 2) + timedelta(hours=5)  # r1 opened it
    assert cal.infer_window_end(loaded, datetime(2026, 10, 1, 16, 0)) is None  # window over


def test_forecast_shows_limit_pct_once_calibrated(loaded):
    for pct in (9.0, 10.0, 11.0):
        cal.save(loaded, [reading(pct, 5)])
    c = cal.fit(loaded)
    f = forecast(pd.DataFrame(), "fix it", model="opus", effort="medium", calibration=c)
    low, med, high = f.estimates[0].limit_pct
    assert low < med < high
    assert med == pytest.approx(c.pct_of_limit(f.estimates[0].total.median))
    assert (
        forecast(pd.DataFrame(), "fix it", model="opus", effort="medium").estimates[0].limit_pct
        is None
    )


WEEK_RESETS = datetime(2026, 10, 5, 9, 0)  # a 7-day window that contains session s1


def weekly_reading(pct, minute):
    return cal.Snapshot("7d", WEEK_RESETS, pct, datetime(2026, 10, 1, 10, minute, 30), "manual")


def test_forecast_shows_weekly_pct_once_calibrated(loaded):
    for pct in (3.0, 4.0, 5.0):
        cal.save(loaded, [weekly_reading(pct, 5)])
    weekly = cal.fit(loaded, "7d")
    assert weekly.ready
    assert weekly.k == pytest.approx(4.0 / (S1_WEIGHTED / 1e6))  # same tokens, 7d readings

    f = forecast(pd.DataFrame(), "fix it", model="opus", effort="medium", weekly=weekly)
    low, med, high = f.weekly_pct
    assert low < med < high
    assert med == pytest.approx(weekly.pct_of_limit(f.estimates[0].total.median))
    assert f.weekly_readings == 3
    assert f.estimates[0].limit_pct is None  # the 5h window has no readings


# -- CLI ---------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKCAST_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TOKCAST_LOGS", str(tmp_path / "no-logs"))  # never read real logs
    return tmp_path / "home"


def test_cli_statusline(home):
    result = runner.invoke(app, ["statusline"], input=json.dumps(PAYLOAD))
    assert result.exit_code == 0
    assert result.output.startswith("tokcast · 5h 24%")
    assert (home / capture.SNAPSHOT_FILE).exists()
    assert runner.invoke(app, ["statusline"], input="garbage").output.strip() == "tokcast"
    assert '"command": "tokcast statusline"' in runner.invoke(app, ["statusline", "--setup"]).output


def test_cli_calibrate_flow(home, logs_dir, monkeypatch):
    runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    # A manual reading "now" is after the fixture's last call, so it waits for newer logs.
    result = runner.invoke(app, ["calibrate", "--used", "12", "--resets-in", "2h10m", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert (data["ready"], data["skipped"]) == (False, 1)

    for bad in (
        ["--window", "1d"],
        ["--used", "5", "--resets-in", "soon"],
        ["--used", "5", "--window", "7d"],
    ):
        assert runner.invoke(app, ["calibrate", *bad]).exit_code == 1


def test_cli_predict_shows_limit_after_three_readings(home, logs_dir):
    from tokcast.storage import db

    runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    with db.connect(home / "tokcast.duckdb") as con:
        for pct in (9.0, 10.0, 11.0):
            cal.save(con, [reading(pct, 5)])
    out = runner.invoke(app, ["predict", "fix the bug"], env={"COLUMNS": "160"}).output
    assert "% of 5h limit" in out
    data = json.loads(runner.invoke(app, ["predict", "fix the bug", "--json"]).output)
    assert data["limit_window"] == "5h" and data["limit_readings"] == 3
    assert data["estimates"][0]["limit_pct"] is not None
    assert (data["weekly_pct"], data["weekly_readings"]) == (None, 0)  # no 7d readings yet
