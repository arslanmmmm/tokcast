import json
import math

import pandas as pd
import pytest
from typer.testing import CliRunner

from tokcast.cli import app
from tokcast.evaluate import MIN_TURNS, backtest, pinball_loss, score, walk_forward_splits
from tokcast.features.build import load_turns
from tokcast.ingest import pipeline
from tokcast.ingest.sources import ClaudeCodeSource
from tokcast.storage import db
from tokcast.synth import generate

runner = CliRunner()


def test_score_by_hand():
    # Four turns that all really cost 100 tokens.
    s = score(
        actual=[100, 100, 100, 100],
        low=[50, 150, 50, 50],  # the 2nd range starts above the actual value: a miss
        median=[100, 200, 100, 400],
        high=[200, 300, 200, 800],
    )
    assert (s.n, s.coverage, s.below, s.above) == (4, 0.75, 0.25, 0.0)
    assert s.within_2x == 0.75  # ratios 1, 2, 1, 4: only the 4x misses
    assert s.bias == pytest.approx(math.sqrt(2))  # median of ratios (1, 1, 2, 4) on a log scale
    assert s.width == pytest.approx(4)  # high/low ratios 4, 2, 4, 16
    assert s.median_error == pytest.approx(0.5)  # |errors| 0, 1, 0, 3 (relative)
    assert s.coverage_margin == pytest.approx(1.96 * math.sqrt(0.75 * 0.25 / 4))


def test_pinball_loss_by_hand():
    assert pinball_loss([1.0], [[1.0]], quantiles=(0.5,)) == 0.0
    assert pinball_loss([1.0], [[0.0]], quantiles=(0.5,)) == 0.5
    # A P90 forecast that is too low is punished 9x harder than one that is too high.
    too_low = pinball_loss([1.0], [[0.0]], quantiles=(0.9,))
    too_high = pinball_loss([0.0], [[1.0]], quantiles=(0.9,))
    assert too_low == pytest.approx(9 * too_high)


def test_walk_forward_never_trains_on_the_future():
    turns = pd.DataFrame({"ts": pd.date_range("2026-01-01", periods=100, freq="h")})
    splits = walk_forward_splits(turns, folds=5, test_fraction=0.5)
    assert [len(train) for train, _ in splits] == [50, 60, 70, 80, 90]
    assert [len(test) for _, test in splits] == [10] * 5
    for train, test in splits:
        assert train["ts"].max() < test["ts"].min()


@pytest.fixture(scope="module")
def synthetic_turns(tmp_path_factory):
    logs = tmp_path_factory.mktemp("synth") / "logs"
    generate(logs, sessions=150, seed=5)
    con = db.connect(":memory:")
    pipeline.ingest(con, ClaudeCodeSource(), logs)
    turns = load_turns(con)
    con.close()
    return turns


def test_backtest_on_synthetic_data(synthetic_turns):
    result = backtest(synthetic_turns, data="synthetic")
    ours = result.method("tokcast baseline").total
    assert 0.7 <= ours.coverage <= 0.9  # calibrated: about 80% inside the 80% range
    assert ours.pinball < result.method("global median").total.pinball
    assert ours.pinball < result.method("context x re-reads").total.pinball
    assert result.method("single call (ctok-style)").total.coverage < 0.5  # ignores the tool loop
    assert result.n_test == round(result.n_turns * 0.5)


def test_backtest_needs_enough_turns(synthetic_turns):
    with pytest.raises(ValueError, match="at least"):
        backtest(synthetic_turns.head(MIN_TURNS - 1), data="synthetic")


# -- CLI ---------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKCAST_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_cli_eval_before_ingest(home):
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 1
    assert "--synthetic" in result.output


def test_cli_eval_with_too_little_history(home, logs_dir):
    runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 1
    assert "Not enough history" in result.output


def test_cli_eval_synthetic_outputs(home):
    data = json.loads(runner.invoke(app, ["eval", "--synthetic", "40", "--json"]).output)
    assert data["data"] == "synthetic"
    assert [m["name"] for m in data["methods"]][-1] == "tokcast baseline"
    md = runner.invoke(app, ["eval", "--synthetic", "40", "--markdown"]).output
    assert "| **tokcast baseline** |" in md
    table = runner.invoke(app, ["eval", "--synthetic", "40"], env={"COLUMNS": "100"}).output
    assert "Synthetic data" in table


def test_cli_eval_labels_a_synthetic_database(home, tmp_path):
    generate(tmp_path / "logs", sessions=40, seed=1)
    runner.invoke(app, ["ingest", "--path", str(tmp_path / "logs")])
    data = json.loads(runner.invoke(app, ["eval", "--json"]).output)
    assert data["data"] == "synthetic"
