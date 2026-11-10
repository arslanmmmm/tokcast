from datetime import timedelta

import pytest

from tokcast import parsing


@pytest.mark.parametrize(
    ("text", "expected"), [("120k", 120_000), ("1.5M", 1_500_000), (" 50000 ", 50_000)]
)
def test_tokens(text, expected):
    assert parsing.tokens(text) == expected


@pytest.mark.parametrize("text", ["lots", "1.2.3k", "", "12g"])
def test_unreadable_tokens_say_what_to_type(text):
    with pytest.raises(ValueError, match=r"try 120k or 1\.5M"):
        parsing.tokens(text)


def test_duration():
    assert parsing.duration("2h10m") == timedelta(hours=2, minutes=10)
    assert parsing.duration("3d4h") == timedelta(days=3, hours=4)


@pytest.mark.parametrize("text", ["soon", "", "10m2h"])
def test_unreadable_durations_say_what_to_type(text):
    with pytest.raises(ValueError, match="try 2h10m"):
        parsing.duration(text)


def test_cli_turns_a_typo_into_one_line_not_a_traceback(tmp_path, monkeypatch):
    # Before tokcast.parsing, "1.2.3k" matched the pattern and then crashed in float().
    from typer.testing import CliRunner

    from tokcast.cli import app

    monkeypatch.setenv("TOKCAST_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TOKCAST_LOGS", str(tmp_path / "no-logs"))

    result = CliRunner().invoke(app, ["predict", "fix it", "--context", "1.2.3k"])

    assert result.exit_code == 1
    assert "Can't read token count: 1.2.3k" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
