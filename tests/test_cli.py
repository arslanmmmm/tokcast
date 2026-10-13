from typer.testing import CliRunner

from tokcast import __version__
from tokcast.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_paths_respects_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKCAST_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TOKCAST_LOGS", str(tmp_path / "logs"))
    # Rich wraps long lines; a wide terminal keeps each path on one line.
    result = runner.invoke(app, ["paths"], env={"COLUMNS": "500"})
    assert result.exit_code == 0
    assert str(tmp_path / "home" / "tokcast.duckdb") in result.output
    assert str(tmp_path / "logs") in result.output


def test_ingest_command_end_to_end(tmp_path, monkeypatch, logs_dir):
    monkeypatch.setenv("TOKCAST_HOME", str(tmp_path / "home"))
    first = runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    assert first.exit_code == 0, first.output
    assert "(+3)" in first.output  # 3 new prompts
    assert "Malformed lines" in first.output

    second = runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    assert "(+0)" in second.output
    assert (tmp_path / "home" / "tokcast.duckdb").exists()


def test_ingest_missing_folder_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKCAST_HOME", str(tmp_path / "home"))
    result = runner.invoke(app, ["ingest", "--path", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "not found" in result.output
