"""Stats on the fixture logs. Expected numbers are worked out by hand from the fixtures:

turn p1 (s1, 2026-10-01 10:00Z): r1 1623 + r2 1611 + subagent ra1 835 + ra2 922 = 4991
turn p2 (s1, 2026-10-01 10:05Z): r4 2 + 3000 + 200 + 40 = 3242
turn L1 (old, 2025-06-01 09:00Z): lr1 490 + lr2 900 + lr3 12 = 1402
"""

import json
from datetime import date, datetime

import pytest
from typer.testing import CliRunner

from tokcast.cli import app
from tokcast.ingest import pipeline
from tokcast.ingest.sources import ClaudeCodeSource
from tokcast.stats import build_report
from tokcast.synth import generate

runner = CliRunner()


@pytest.fixture
def loaded(con, logs_dir):
    con.execute("SET TimeZone = 'UTC'")
    pipeline.ingest(con, ClaudeCodeSource(), logs_dir)
    return con


def test_overview(loaded):
    o = build_report(loaded).overview
    assert (o["sessions"], o["turns"], o["api_calls"]) == (2, 3, 8)
    assert o["total_tokens"] == 4991 + 3242 + 1402
    assert o["output_tokens"] == 230 + 40 + 397
    assert o["cache_read_tokens"] == 1000 + 1500 + 3000 + 800
    assert o["subagent_tokens"] == 835 + 922
    assert o["median_turn_tokens"] == 3242


def test_by_model_counts_each_call_under_its_own_model(loaded):
    rows = {r["model"]: r for r in build_report(loaded).by_model}
    assert list(rows) == ["sonnet", "haiku", "opus"]  # ordered by tokens
    assert (rows["sonnet"]["effort"], rows["sonnet"]["turns"], rows["sonnet"]["api_calls"]) == (
        "high",
        2,
        3,
    )
    assert rows["haiku"]["total_tokens"] == 835 + 922  # the subagent, inside a sonnet turn
    assert rows["haiku"]["effort"] == "subagent"
    assert sum(r["share_pct"] for r in rows.values()) == pytest.approx(100, abs=0.2)


def test_by_day_uses_the_session_time_zone(loaded):
    days = [(r["day"], r["turns"]) for r in build_report(loaded).by_day]
    assert days == [(date(2025, 6, 1), 1), (date(2026, 10, 1), 2)]

    loaded.execute("SET TimeZone = 'Pacific/Kiritimati'")  # UTC+14: 10:00Z is midnight next day
    days = [r["day"] for r in build_report(loaded).by_day]
    assert days == [date(2025, 6, 1), date(2026, 10, 2)]


def test_projects_and_top_sessions(loaded):
    report = build_report(loaded, top=1)
    assert [(r["project"], r["turns"]) for r in report.by_project] == [("myapp", 2), ("legacy", 1)]
    [top] = report.top_sessions
    assert (top["session_id"], top["total_tokens"]) == ("s1", 4991 + 3242)
    assert top["first_prompt"] == "fix the login bug in auth.py"


def test_days_filter(loaded):
    report = build_report(loaded, days=30, now=datetime(2026, 10, 10))
    assert (report.overview["turns"], report.overview["api_calls"]) == (2, 5)
    assert report.overview["total_tokens"] == 4991 + 3242
    assert {r["model"] for r in report.by_model} == {"sonnet", "haiku"}


def test_context_and_turn_length_sections(loaded):
    report = build_report(loaded)
    # Main-agent calls only (subagents excluded); all fixture contexts are small.
    assert [(r["context_size"], r["api_calls"]) for r in report.context_cost] == [("< 50k", 6)]
    assert report.context_cost_ratio is None  # needs at least two buckets
    assert [(r["turn_number"], r["turns"]) for r in report.turn_length] == [("1", 2), ("2-5", 1)]


def test_data_quality_by_version(loaded, tmp_path):
    rows = {r["version"]: r for r in build_report(loaded).data_quality}
    assert {v: (r["api_calls"], r["flagged"]) for v, r in rows.items()} == {
        "1.0.40": (3, 0),
        "2.1.295": (5, 0),
    }
    # A call whose thinking count exceeds its output count can't be right.
    bad = tmp_path / "bad" / "proj"
    bad.mkdir(parents=True)
    (bad / "b.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "uuid": "b1",
                "sessionId": "b",
                "version": "9.9.9",
                "requestId": "rb",
                "message": {
                    "model": "claude-opus-5-5",
                    "usage": {
                        "input_tokens": 5,
                        "output_tokens": 3,
                        "output_tokens_details": {"thinking_tokens": 50},
                    },
                },
            }
        )
        + "\n"
    )
    pipeline.ingest(loaded, ClaudeCodeSource(), tmp_path / "bad")
    rows = {r["version"]: r for r in build_report(loaded).data_quality}
    assert (rows["9.9.9"]["flagged"], rows["9.9.9"]["thinking_exceeds_output"]) == (1, 1)


def test_call_cost_grows_with_context_on_synthetic_data(tmp_path):
    from tokcast.storage import db

    generate(tmp_path / "logs", sessions=30, seed=3)
    con = db.connect(":memory:")
    pipeline.ingest(con, ClaudeCodeSource(), tmp_path / "logs")
    medians = [r["median_call_tokens"] for r in build_report(con).context_cost]
    assert len(medians) >= 3
    assert medians == sorted(medians)
    con.close()


# -- CLI ---------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKCAST_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_cli_stats_before_ingest(home):
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 1
    assert "tokcast ingest" in result.output


def test_cli_stats_tables_and_json(home, logs_dir):
    runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    result = runner.invoke(app, ["stats", "--tz", "UTC"], env={"COLUMNS": "120"})
    assert result.exit_code == 0, result.output
    for title in ("By model and effort", "By day", "By project", "Most expensive sessions"):
        assert title in result.output
    assert "Data quality: no suspicious usage values in 8 API calls" in result.output

    data = json.loads(runner.invoke(app, ["stats", "--json"]).output)
    assert data["overview"]["turns"] == 3
    assert data["top_sessions"][0]["session_id"] == "s1"


def test_cli_stats_rejects_unknown_time_zone(home, logs_dir):
    runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    result = runner.invoke(app, ["stats", "--tz", "Mars/Olympus"])
    assert result.exit_code == 1
    assert "Unknown time zone" in result.output


def test_cli_stats_empty_period(home, logs_dir):
    runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    result = runner.invoke(app, ["stats", "--days", "1"])
    assert result.exit_code == 0
    assert "No turns in this period" in result.output
