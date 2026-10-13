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
