import builtins
import json

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from tokcast.cli import app
from tokcast.evaluate import backtest
from tokcast.evaluate.reference import all_methods, ml_available
from tokcast.predict import BaselinePredictor, Query
from tokcast.predict.qreg import FEATURES, MIN_TRAIN, QuantileRegressionPredictor, feature_matrix

pytestmark = pytest.mark.skipif(not ml_available(), reason="needs the ml extra")
runner = CliRunner()


def q(model="sonnet", effort="medium", task="bugfix", first=False, context=150_000):
    return Query(task, model, effort, first, context, prompt_tokens=20)


def test_feature_matrix_one_hot_with_reference_levels():
    rows = pd.DataFrame(
        {
            "task_type": ["other", "bugfix"],
            "model": ["sonnet", "opus"],
            "effort": ["medium", "high"],
            "first_turn": [False, True],
            "context": [1_000, np.e**12],
            "prompt_tokens": [0, 10],
        }
    )
    x = feature_matrix(rows)
    assert x.shape == (2, len(FEATURES))
    # Row 0 uses only reference levels: every one-hot column is 0.
    one_hot = [i for i, f in enumerate(FEATURES) if "=" in f]
    assert x[0, one_hot].sum() == 0
    row1 = dict(zip(FEATURES, x[1], strict=True))
    assert row1["task_type=bugfix"] == row1["model=opus"] == row1["effort=high"] == 1
    assert row1["first_turn"] == 1 and row1["log_context"] == pytest.approx(12)


def test_hands_over_to_the_baseline_with_little_history(synthetic_turns):
    small = synthetic_turns.head(MIN_TRAIN - 1)
    qr = QuantileRegressionPredictor().fit(small)
    assert qr.predict(q()) == BaselinePredictor().fit(small).predict(q())


def test_hands_over_for_unseen_models(synthetic_turns):
    sonnet_only = synthetic_turns[synthetic_turns["model"] == "sonnet"]
    qr = QuantileRegressionPredictor().fit(sonnet_only)
    assert qr.predict(q()).level == "regression"
    assert qr.predict(q(model="fable")) == BaselinePredictor().fit(sonnet_only).predict(
        q(model="fable")
    )


def test_batch_and_single_predictions_agree_and_are_ordered(synthetic_turns):
    qr = QuantileRegressionPredictor().fit(synthetic_turns)
    queries = [q(), q(model="opus", effort="high"), q(task="explain", first=True, context=40_000)]
    batch = qr.predict_many(queries)
    assert batch == [qr.predict(x) for x in queries]
    for e in batch:
        assert e.total.low <= e.total.median <= e.total.high
        assert e.output.low <= e.output.median <= e.output.high


def test_linear_regression_is_calibrated_on_synthetic_data(synthetic_turns):
    from tokcast.evaluate.reference import Baseline, LinearQR

    result = backtest(synthetic_turns, data="synthetic", methods=[Baseline, LinearQR])
    qr = result.method("quantile regression (linear)")
    assert 0.7 <= qr.total.coverage <= 0.9
    assert qr.vs_baseline is not None


def test_regression_is_optional(monkeypatch):
    real_import = builtins.__import__

    def no_sklearn(name, *args, **kwargs):
        if name.startswith("sklearn"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sklearn)
    assert not ml_available()
    assert [m.name for m in all_methods()][-1] == "tokcast baseline"
    result = runner.invoke(app, ["predict", "fix it", "--method", "qreg"])
    assert result.exit_code == 1
    assert "tokcast[ml]" in result.output


def test_cli_predict_with_qreg(tmp_path, monkeypatch, logs_dir):
    monkeypatch.setenv("TOKCAST_HOME", str(tmp_path / "home"))
    runner.invoke(app, ["ingest", "--path", str(logs_dir)])
    data = json.loads(
        runner.invoke(app, ["predict", "fix it", "--method", "qreg", "--json"]).output
    )
    assert data["estimates"][0]["level"] != "regression"  # 3 turns: handed over to the baseline
    assert runner.invoke(app, ["predict", "fix it", "--method", "magic"]).exit_code == 1
