import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tokcast.cli import app
from tokcast.ingest import pipeline
from tokcast.ingest.sources import ClaudeCodeSource
from tokcast.synth import MARKER_FILE, generate, is_synthetic

runner = CliRunner()


def digest(folder: Path) -> str:
    """One hash over every file's path and bytes."""
    h = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            h.update(str(path.relative_to(folder)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def synth_db(tmp_path_factory):
    """40 synthetic sessions, generated once and ingested into an in-memory database."""
    from tokcast.storage import db

    logs = tmp_path_factory.mktemp("synth") / "logs"
    summary = generate(logs, sessions=40, seed=7)
    con = db.connect(":memory:")
    report = pipeline.ingest(con, ClaudeCodeSource(), logs)
    yield summary, report, con
    con.close()


def test_same_seed_gives_identical_files(tmp_path):
    generate(tmp_path / "a", sessions=5, seed=1)
    generate(tmp_path / "b", sessions=5, seed=1)
    generate(tmp_path / "c", sessions=5, seed=2)
    assert digest(tmp_path / "a") == digest(tmp_path / "b")
    assert digest(tmp_path / "a") != digest(tmp_path / "c")


def test_ingest_reproduces_the_generator_counts(synth_db):
    summary, report, con = synth_db
    assert report.prompts_after == summary.prompts
    assert report.requests_after == summary.requests + summary.subagent_requests
    assert report.errors == summary.malformed_lines
    n_sub = con.execute("SELECT count(*) FROM requests WHERE agent_id IS NOT NULL").fetchone()[0]
    assert n_sub == summary.subagent_requests > 0


def test_every_turn_total_matches_ground_truth(synth_db):
    # The strongest end-to-end check: dedupe, streaming partials, turn linking (including
    # subagents via the ASOF join) and the token definition all have to be right.
    summary, _, con = synth_db
    loaded = dict(con.execute("SELECT turn_id, total_tokens FROM turns").fetchall())
    assert loaded == summary.turn_totals


def test_no_request_is_left_without_a_turn(synth_db):
    _, _, con = synth_db
    assert con.execute("SELECT count(*) FROM v_requests WHERE turn_id IS NULL").fetchone() == (0,)


def test_synthetic_data_has_the_intended_structure(synth_db):
    _, _, con = synth_db

    def median_calls(where: str) -> float:
        return con.execute(f"SELECT median(n_requests) FROM turns WHERE {where}").fetchone()[0]

    # More effort -> more API calls; a feature -> more calls than a quick shell command.
    assert median_calls("effort IN ('high', 'xhigh', 'max')") > median_calls("effort = 'low'")
    assert median_calls("text LIKE '%implement%' OR text LIKE '%add %'") > median_calls(
        "kind = 'bash-input'"
    )
    models = {m for (m,) in con.execute("SELECT DISTINCT model_family FROM turns").fetchall()}
    assert models == {"opus", "sonnet", "haiku"}


def test_marker_detection(tmp_path):
    assert not is_synthetic(tmp_path)
    generate(tmp_path / "logs", sessions=1, seed=1)
    assert (tmp_path / "logs" / MARKER_FILE).exists()
    assert is_synthetic(tmp_path / "logs")
    (tmp_path / "logs" / MARKER_FILE).unlink()
    assert is_synthetic(tmp_path / "logs")  # project folders give it away too


def test_cli_synth_then_ingest_into_a_separate_database(tmp_path, monkeypatch):
    out = tmp_path / "demo"
    result = runner.invoke(app, ["synth", "--out", str(out), "--sessions", "3", "--seed", "1"])
    assert result.exit_code == 0, result.output
    assert "synthetic" in result.output

    # Without TOKCAST_HOME, ingest would write to the real database: refused.
    monkeypatch.delenv("TOKCAST_HOME", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))  # never touch the real one
    refused = runner.invoke(app, ["ingest", "--path", str(out / "logs")])
    assert refused.exit_code == 1
    assert "synthetic" in refused.output
    assert not (tmp_path / "xdg").exists()

    monkeypatch.setenv("TOKCAST_HOME", str(out / "db"))
    loaded = runner.invoke(app, ["ingest", "--path", str(out / "logs")])
    assert loaded.exit_code == 0, loaded.output


def test_cli_synth_refuses_to_overwrite(tmp_path):
    out = tmp_path / "demo"
    (out / "logs").mkdir(parents=True)
    (out / "logs" / "real.jsonl").write_text("{}\n")  # not ours
    args = ["synth", "--out", str(out), "--sessions", "1"]
    assert runner.invoke(app, args).exit_code == 1
    assert runner.invoke(app, [*args, "--force"]).exit_code == 1  # still not ours
    assert (out / "logs" / "real.jsonl").exists()
